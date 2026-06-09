import type { FastifyInstance } from 'fastify';

export async function healthHandler(app: FastifyInstance): Promise<void> {
  app.get('/health', async (_request, reply) => {
    const templateCount = Object.keys(app.registry).length;

    if (templateCount === 0) {
      return reply.code(503).send({
        status: 'error',
        message: 'Registry is empty',
      });
    }

    return reply.send({ status: 'ok', templates: templateCount });
  });
}
