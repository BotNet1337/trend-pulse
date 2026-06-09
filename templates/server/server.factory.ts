import fastify, { type FastifyInstance } from 'fastify';
import type { AppConfig } from './config.js';
import { loggerOptions } from './logger.js';
import { loadRegistry } from './registry.js';
import { healthHandler } from './handlers/health.handler.js';
import { renderHandler } from './handlers/render.handler.js';
import './types.js';

export class ServerFactory {
  private readonly config: AppConfig;

  constructor(config: AppConfig) {
    this.config = config;
  }

  async create(): Promise<FastifyInstance> {
    const app = fastify({
      logger:
        loggerOptions.byEnv[
          this.config.NODE_ENV as keyof typeof loggerOptions.byEnv
        ] ?? true,
    });

    const registry = await loadRegistry(this.config.SCHEMA_PATH);
    app.decorate('appConfig', this.config);
    app.decorate('registry', registry);

    app.register(healthHandler);
    app.register(renderHandler);

    if (this.config.NODE_ENV !== 'production') {
      const { previewHandler } = await import('./handlers/preview.handler.js');
      app.register(previewHandler);
    }

    return app;
  }
}
