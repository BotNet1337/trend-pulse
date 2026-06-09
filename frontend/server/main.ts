import { FastifyInstance } from 'fastify';
import { loadConfig } from './config.js';
import { ServerFactory } from './server.factory.js';
import { config } from 'dotenv'

config()

if (!import.meta.env) {
  (import.meta as { env: Record<string, string | boolean> }).env = {
    DEV: process.env.NODE_ENV !== 'production',
    PROD: process.env.NODE_ENV === 'production',
    SSR: true,
    MODE: process.env.NODE_ENV ?? 'production',
  };
}

// Forced-exit safety net: if `app.close()` does not drain in-flight requests
// within this window we bail out hard. Kept just under the container's
// `stop_grace_period: 10s` (release/docker-compose.frontend.yml) so we exit
// before Docker escalates to SIGKILL. No `ms` helper in the frontend deps, so
// a named const with a comment instead of magic arithmetic.
const DRAIN_TIMEOUT_MS = 5000;

function registerShutdownHandlers(app: FastifyInstance) {
  let shuttingDown = false;

  const shutdown = async (signal: NodeJS.Signals) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;

    app.log.info({ signal }, 'graceful shutdown started, draining in-flight requests');

    const forceExit = setTimeout(() => {
      app.log.warn({ signal, timeoutMs: DRAIN_TIMEOUT_MS }, 'drain timed out, forcing exit');
      process.exit(1);
    }, DRAIN_TIMEOUT_MS);
    forceExit.unref();

    try {
      await app.close();
      app.log.info({ signal }, 'graceful shutdown complete');
      process.exit(0);
    } catch (err) {
      app.log.error({ err, signal }, 'error during graceful shutdown');
      process.exit(1);
    }
  };

  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));
}

async function bootstrap() {
  const config = loadConfig.from.env(process.env);
  const factory = new ServerFactory(config);
  const app = await factory.create();

  registerShutdownHandlers(app);

  await app.listen({
    port: config.PORT ?? 5173,
    host: '0.0.0.0',
  });
}

bootstrap().catch((err) => {
  console.error(err);
  process.exit(1);
});
