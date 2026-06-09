import { config as loadDotenv } from 'dotenv';
import { loadConfig } from './config.js';
import { ServerFactory } from './server.factory.js';

loadDotenv();

async function bootstrap(): Promise<void> {
  const config = loadConfig.from.env(process.env);
  const app = await new ServerFactory(config).create();

  await app.listen({ port: config.PORT, host: '0.0.0.0' });
}

bootstrap().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
