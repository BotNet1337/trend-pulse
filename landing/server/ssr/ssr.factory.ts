import type { FastifyBaseLogger, FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import type { ViteDevServer } from 'vite';
import { createServer as createViteServer } from 'vite';
import { buildHtml } from './html';
import type { RenderFn, RenderFnInput, RenderPayload } from './ssr.types.ts';
import { loadConfig } from '../config.js';
import { createCasesService, type CasesService } from '../cases.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const devIndexHtmlPath = path.resolve(process.cwd(), 'index.html');
const prodIndexHtmlPath = path.resolve(__dirname, '../../dist/client/index.html');

type AppConfig = ReturnType<typeof loadConfig.from.env>;

type ProdAssets = {
  template: string;
  render: RenderFn;
};

export class SsrFactory {
  private readonly config: AppConfig;
  private readonly isProd: boolean;

  private server?: ViteDevServer;
  private prodAssets?: ProdAssets;
  private logger?: FastifyBaseLogger;
  private readonly casesService: CasesService;

  constructor(config: AppConfig, logger?: FastifyBaseLogger) {
    this.config = config;
    this.isProd = this.config.NODE_ENV === 'production';
    this.logger = logger;
    // TASK-067: proof-of-speed cases — SSR-side fetch with in-memory cache.
    this.casesService = createCasesService({
      apiUrl: this.config.CASES_API_URL,
      cacheTtlSeconds: this.config.CASES_CACHE_TTL_SECONDS,
      fetchTimeoutMs: this.config.CASES_FETCH_TIMEOUT_MS,
      logger,
    });
  }

  async setup(app: FastifyInstance): Promise<void> {
    if (!this.isProd) {
      this.server = await this.createDevViteServer();
      app.use(this.server.middlewares);
    } else {
      this.prodAssets = await this.loadProdAssets();
    }
  }

  getHandler() {
    return (req: FastifyRequest, reply: FastifyReply) => this.handleRequest(req, reply);
  }

  private async createDevViteServer(): Promise<ViteDevServer> {
    return createViteServer({
      root: process.cwd(),
      server: { middlewareMode: true },
      appType: 'custom',
    });
  }

  private async loadProdAssets(): Promise<ProdAssets> {
    const template = await fs.readFile(prodIndexHtmlPath, 'utf8');
    // In production we import the Vite SSR build output (so TS path aliases work).
    const candidates = [
      path.resolve(process.cwd(), 'dist/server/server/ssr/render.js'),
      path.resolve(process.cwd(), 'dist/server/ssr/render.js'),
      path.resolve(process.cwd(), 'dist/server/render.js'),
    ];

    let entry: string | null = null;
    for (const p of candidates) {
      try {
         
        await fs.stat(p);
        entry = p;
        break;
      } catch {
        // ignore
      }
    }

    if (!entry) {
      throw new Error(
        `[landing] SSR bundle not found. Tried:\n${candidates.map((p) => `- ${p}`).join('\n')}`,
      );
    }

    const mod = await import(pathToFileURL(entry).href);
    return { template, render: mod.render as RenderFn };
  }

  private async loadDevAssets(url: string): Promise<ProdAssets> {
    if (!this.server) throw new Error('Vite dev server is not initialized');

    const rawTemplate = await fs.readFile(devIndexHtmlPath, 'utf8');
    const template = await this.server.transformIndexHtml(url, rawTemplate);
    const { render } = await this.server.ssrLoadModule('/server/ssr/render.tsx');

    return { template, render: render as RenderFn };
  }

  private async selectAssets(url: string): Promise<ProdAssets> {
    if (!this.isProd && this.server) return this.loadDevAssets(url);
    if (this.prodAssets) return this.prodAssets;
    this.prodAssets = await this.loadProdAssets();
    return this.prodAssets;
  }

  private async handleRequest(req: FastifyRequest, reply: FastifyReply): Promise<void> {
    const url = req.raw.url || '/';
    const start = Date.now();

    if (!this.isProd) {
      try {
        const pathname = new URL(url, 'http://localhost').pathname;
        this.logger?.info({ url, pathname, method: req.method }, 'ssr_dev_request');
      } catch {
        this.logger?.info({ url, method: req.method }, 'ssr_dev_request');
      }
    }

    // Check if response was already sent by Vite middleware
    if (reply.sent) {
      return;
    }

    try {
      const { template, render } = await this.selectAssets(url);

      // Never throws: cases.ts catches every failure and yields [] (section hidden).
      const cases = await this.casesService.getCases();

      const renderPayload: RenderFnInput = {
        url,
        ctx: {
          requestId: req.id,
        },
        cases,
      };

      const payload: RenderPayload = await render(renderPayload);

      if (payload.redirect) {
        return reply.redirect(payload.redirect.location, payload.redirect.status);
      }

      const html = buildHtml(template, payload);

      const status = payload.statusCode ?? 200;
      reply.header('Cache-Control', 'no-store');
      reply.type('text/html').status(status).send(html);

      this.logger?.info(
        { method: req.method, url, status, ms: Date.now() - start, ua: req.headers['user-agent'] },
        'http_request',
      );
    } catch (error) {
      if (reply.sent) {
        return;
      }
      if (!this.isProd && this.server && error instanceof Error) {
        this.server.ssrFixStacktrace(error);
      }
      this.logger?.error({ error, url }, 'ssr_error');
      reply.status(500).send('Internal Server Error');
    }
  }
}


