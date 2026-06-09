import type { FastifyInstance } from 'fastify';
import middie from '@fastify/middie';
import { AppConfig } from '../config';

export class MiddlewaresFactory {
  private readonly config: AppConfig;

  constructor(config: AppConfig) {
    this.config = config;
  }

  async apply(app: FastifyInstance): Promise<void> {
    await app.register(middie);
  }
}
