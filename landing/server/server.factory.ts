import fastify, { type FastifyInstance } from 'fastify';
import compress from '@fastify/compress';
import fastifyStatic from '@fastify/static';
import path from 'node:path';
import { MiddlewaresFactory } from './middlewares/middlewares.factory.js';
import { SsrFactory } from './ssr/ssr.factory.js';
import { loggerOptions } from './logger.js';
import type { AppConfig } from './config.js';
import { z } from 'zod';

const waitlistSchema = z.object({
  email: z.string().email(),
  name: z.string().trim().min(1).max(120).optional(),
});

type WaitlistSubmission = z.infer<typeof waitlistSchema> & { at: string; ip?: string };

export class ServerFactory {
  private readonly config: AppConfig;

  constructor(config: AppConfig) {
    this.config = config;
  }

  async create(): Promise<FastifyInstance> {
    const app = fastify({
      logger: loggerOptions.byEnv[this.config.NODE_ENV] ?? true,
      requestTimeout: 30_000,
    });

    const middlewaresFactory = new MiddlewaresFactory();
    await middlewaresFactory.apply(app);

    const submissions: WaitlistSubmission[] = [];

    app.post('/api/waitlist', async (req, reply) => {
      const parsed = waitlistSchema.safeParse(req.body);
      if (!parsed.success) {
        req.log.info({ issues: parsed.error.issues }, 'waitlist_invalid');
        return reply.status(400).send({ ok: false, error: 'Invalid payload' });
      }

      const submission: WaitlistSubmission = {
        ...parsed.data,
        at: new Date().toISOString(),
        ip: req.ip,
      };

      submissions.push(submission);
      req.log.info({ email: submission.email }, 'waitlist_submitted');

      return reply.send({ ok: true });
    });

    const ssrFactory = new SsrFactory(this.config, app.log);
    await ssrFactory.setup(app);

    // In prod, serve client assets + fall through to SSR (no wildcard static 404s)
    if (this.config.NODE_ENV === 'production') {
      // Serve built client assets in prod
      await app.register(fastifyStatic, {
        root: path.resolve(process.cwd(), 'dist/client'),
        prefix: '/',
        wildcard: false,
        index: false,
        cacheControl: true,
        etag: true,
        maxAge: '1y',
        immutable: true,
      });

      const ssrHandler = ssrFactory.getHandler();
      app.setNotFoundHandler((req, reply) => {
        // Don't SSR non-GET requests.
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          return reply.status(404).send('Not Found');
        }

        // Keep API behavior predictable.
        if (req.url.startsWith('/api/')) {
          return reply.status(404).send({ ok: false, error: 'Not Found' });
        }

        return ssrHandler(req, reply);
      });
    }
    // In dev, Vite middleware handles static files and we route all GETs to SSR.
    if (this.config.NODE_ENV !== 'production') {
      app.get('*', ssrFactory.getHandler());
    }

    // Register compress after routes to avoid interfering with Vite middleware
    await app.register(compress, { global: true });

    return app;
  }
}


