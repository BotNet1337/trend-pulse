import type { FastifyInstance } from 'fastify';
import middie from '@fastify/middie';

export class MiddlewaresFactory {
  constructor() {}

  async apply(app: FastifyInstance): Promise<void> {
    await app.register(middie);
  }
}


