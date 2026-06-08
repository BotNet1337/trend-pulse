import { config as dotenvConfig } from 'dotenv';
import { loadConfig } from './config.js';
import { ServerFactory } from './server.factory.js';

dotenvConfig();

async function bootstrap() {
  const cfg = loadConfig.from.env(process.env);
  const factory = new ServerFactory(cfg);
  const app = await factory.create();

  await app.listen({
    port: cfg.PORT ?? 5174,
    host: '0.0.0.0',
  });
}

bootstrap().catch((err) => {
  console.error(err);
  process.exit(1);
});


