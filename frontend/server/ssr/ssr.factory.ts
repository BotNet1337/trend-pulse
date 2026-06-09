import type { FastifyBaseLogger, FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ViteDevServer } from 'vite';
import { buildHtml } from './html';
import type { RenderFn, RenderFnInput, RenderPayload } from './ssr.types.ts';
import { loadConfig } from '../config.js';

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

  constructor(config: AppConfig, logger?: FastifyBaseLogger) {
    this.config = config;
    this.isProd = this.config.NODE_ENV === 'production';
    this.logger = logger;
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
    return (req: FastifyRequest, reply: FastifyReply) =>
      this.handleRequest(req, reply);
  }

  private async createDevViteServer(): Promise<ViteDevServer> {
    // Dynamic import so the production runtime never resolves `vite` at all
    // (prod serves prebuilt dist/client + render.js; vite is a dev-only dep).
    const { createServer: createViteServer } = await import('vite');
    return createViteServer({
      root: process.cwd(),
      server: {
        middlewareMode: true,
        // Vite крутится в middleware-режиме внутри Fastify; HMR-сокет
        // поднимается отдельно на порту 24678 (см. vite.config.ts →
        // server.hmr) и проксируется nginx через /__vite_hmr — Fastify
        // catch-all его не перехватывает.
      },
      appType: 'custom',
    });
  }

  private async loadProdAssets(): Promise<ProdAssets> {
    const template = await fs.readFile(prodIndexHtmlPath, 'utf8');

    const { render } = await import('./render.js');
    return { template, render: render as RenderFn };
  }

  private async loadDevAssets(url: string): Promise<ProdAssets> {
    if (!this.server) {
      throw new Error('Vite dev server is not initialized');
    }

    const rawTemplate = await fs.readFile(devIndexHtmlPath, 'utf8');
    const template = await this.server.transformIndexHtml(url, rawTemplate);

    const { render } = await this.server.ssrLoadModule('/server/ssr/render.tsx');

    return { template, render: render as RenderFn };
  }

  private async selectAssets(url: string): Promise<ProdAssets> {
    if (!this.isProd && this.server) {
      return this.loadDevAssets(url);
    }

    if (this.prodAssets) {
      return this.prodAssets;
    }

    this.prodAssets = await this.loadProdAssets();
    return this.prodAssets;
  }

  private async handleRequest(
    req: FastifyRequest,
    reply: FastifyReply
  ): Promise<void> {
    const url = req.raw.url || '/';
    try {
      const { template, render } = await this.selectAssets(url);

      // Forward the raw Cookie header to the prefetch layer.
      // The httpOnly `fastapiusersauth` cookie is included here and will be
      // forwarded verbatim to the upstream API in fetchCurrentUser / fetchWatchlists.
      // We do NOT decode the cookie or inject any Bearer token.
      const cookieHeader = req.headers.cookie;
      this.logger?.debug({ hasCookie: !!cookieHeader }, 'SSR request cookie present');

      const renderPayload: RenderFnInput = {
        url,
        ctx: {
          cookieHeader,
        }
      }

      const payload: RenderPayload = await render(renderPayload);

      if (payload.redirect) {
        return reply.redirect(payload.redirect.location, payload.redirect.status);
      }

      const cspNonce = (reply as unknown as { cspNonce?: { script: string } })
        .cspNonce?.script;
      const html = buildHtml(template, payload, { cspNonce, logger: this.logger });

      reply.type('text/html').send(html);
    } catch (error) {
      if (!this.isProd && this.server && error instanceof Error) {
        this.server.ssrFixStacktrace(error);
      }
      this.logger?.error({ error }, 'Internal server error');
      reply.status(500).send('Internal Server Error');
    }
  }
}
