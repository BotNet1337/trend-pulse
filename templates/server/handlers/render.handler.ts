import type { FastifyInstance } from 'fastify';
import { renderEntry } from '../registry.js';

export async function renderHandler(app: FastifyInstance): Promise<void> {
  app.post<{ Params: { '*': string } }>('/render/*', async (request, reply) => {
    const templatePath = request.params['*'];

    if (!templatePath) {
      return reply.code(400).send({ error: 'Template path is required' });
    }

    const entry = app.registry[templatePath];
    if (!entry) {
      return reply.code(404).send({ error: 'Template not found' });
    }

    const parsed = entry.schema.safeParse(request.body);
    if (!parsed.success) {
      return reply.code(400).send({
        error: 'Invalid props',
        issues: parsed.error.issues,
      });
    }

    const raw = parsed.data as Record<string, unknown>;
    const result = await renderEntry(entry, raw, app.appConfig);
    return reply.send(result);
  });
}
