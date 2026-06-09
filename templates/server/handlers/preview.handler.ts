import type { FastifyInstance } from 'fastify';
import { renderEntry } from '../registry.js';
import { mergePreviewQuery } from '../utils.js';

export async function previewHandler(app: FastifyInstance): Promise<void> {
  app.get<{ Params: { '*': string } }>('/preview/*', async (request, reply) => {
    const templatePath = request.params['*'];

    if (!templatePath || !app.registry[templatePath]) {
      return reply.code(404).send('Template not found');
    }

    const entry = app.registry[templatePath];
    const query = request.query as Record<string, string | string[] | undefined>;
    const merged = mergePreviewQuery(entry.previewDefaults, query);

    const parsed = entry.schema.safeParse(merged);
    if (!parsed.success) {
      return reply
        .code(400)
        .type('text/plain')
        .send(JSON.stringify(parsed.error.issues, null, 2));
    }

    const raw = parsed.data as Record<string, unknown>;
    const result = await renderEntry(entry, raw, app.appConfig);
    return reply.type('text/html').send(result.html);
  });
}
