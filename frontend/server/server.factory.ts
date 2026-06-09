import fastify, { FastifyInstance } from 'fastify';
import fastifyHttpProxy from '@fastify/http-proxy';
import fastifyStatic from '@fastify/static';
import helmet from '@fastify/helmet';
import path from 'node:path';
import { MiddlewaresFactory } from './middlewares/middlewares.factory.js';
import { SsrFactory } from './ssr/ssr.factory.js';
import { loggerOptions } from './logger.js';
import { AppConfig } from './config.js';
import cookie from '@fastify/cookie'
import authPlugin from './plugins/auth.plugin.js';
import refreshPlugin from './plugins/refresh.plugin.js';



export class ServerFactory {
  private readonly config: AppConfig;

  constructor(config: AppConfig) {
    this.config = config;
  }

  async create(): Promise<FastifyInstance> {
    const app = fastify({
      logger: loggerOptions.byEnv[this.config.NODE_ENV] ?? true
    });

    app.register(cookie, { secret: this.config.COOKIE_SECRET })

    // SECURITY (TASK-AUDIT-RELEASE-1 / C5):
    // Helmet sets default security headers (X-Frame-Options, X-Content-Type-
    // Options, Strict-Transport-Security, Referrer-Policy, etc.) and a CSP.
    //
    // In production we run with `enableCSPNonces: true`: helmet stamps a
    // per-request nonce onto `script-src`/`style-src`, and the SSR layer
    // reads `reply.cspNonce.script` to stamp the inline `__INITIAL_STATE__`
    // `<script>`. Per spec, when a nonce is present in a directive the
    // browser ignores `'unsafe-inline'`.
    //
    // In dev that exact behaviour breaks Vite's HMR, which injects inline
    // `<style>` (and occasionally `<script>`) tags without our nonce. The
    // browser blocks them, reporting the familiar
    //   "Applying inline style violates … 'nonce-…'"
    // We disable nonces in dev and rely on `'unsafe-inline'`/`'unsafe-eval'`
    // to keep HMR working — the dev server is local-only behind mkcert, so
    // the relaxed CSP is acceptable.
    const isProd = this.config.NODE_ENV === 'production';
    await app.register(helmet, {
      enableCSPNonces: isProd,
      contentSecurityPolicy: {
        useDefaults: true,
        directives: {
          'default-src': ["'self'"],
          'script-src': isProd
            ? ["'self'"]
            : ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
          'style-src': ["'self'", "'unsafe-inline'", 'https:', 'data:'],
          'img-src': ["'self'", 'data:', 'blob:', 'https:'],
          'media-src': ["'self'", 'data:', 'blob:', 'https:'],
          'font-src': ["'self'", 'data:', 'https:'],
          'connect-src': ["'self'", 'https:', 'wss:', 'ws:'],
          'frame-ancestors': ["'none'"],
          'object-src': ["'none'"],
          'base-uri': ["'self'"],
          'form-action': ["'self'"],
        },
      },
      crossOriginEmbedderPolicy: false,
      crossOriginResourcePolicy: { policy: 'same-site' },
    });

    // @fastify/helmet `enableCSPNonces` pushes a nonce into both script-src
    // AND style-src. Per CSP spec, once a nonce is present the browser ignores
    // 'unsafe-inline', which breaks every inline `style=""` attribute React
    // emits. Strip the style nonce so 'unsafe-inline' keeps working for styles.
    if (isProd) {
      app.addHook('onSend', async (_req, reply, payload) => {
        const styleNonce = (reply as unknown as { cspNonce?: { style: string } })
          .cspNonce?.style;
        if (styleNonce) {
          const csp = reply.raw.getHeader('content-security-policy');
          if (typeof csp === 'string') {
            reply.raw.setHeader(
              'content-security-policy',
              csp.replace(` 'nonce-${styleNonce}'`, ''),
            );
          }
        }
        return payload;
      });
    }

    app.register(fastifyHttpProxy, {
      upstream: this.config.API_URL,
      prefix: '/api',
      rewritePrefix: '',
      proxyPayloads: true,
      replyOptions: {
        rewriteRequestHeaders: (originalReq, headers) => {
          const cookies = originalReq.cookies ?? '';
          const accessToken = cookies?.access_token;
          const refreshToken = cookies?.refresh_token;

          const nextHeaders: Record<string, string> = {
            ...(headers as Record<string, string>),
          };

          if (accessToken) {
            nextHeaders.authorization = `Bearer ${accessToken}`;
          } else if (refreshToken) {
            nextHeaders.authorization = `Bearer ${refreshToken}`;
          }

          return nextHeaders;
        },
      },
    })

    // Socket.io upgrade. The WS gateway lives on the API host on path
    // `/socket.io/` (default) with namespace `/ws`. Browser cookies (incl.
    // `access_token`) ride along on the same-origin upgrade — the gateway
    // reads them from `handshake.headers.cookie`.
    app.register(fastifyHttpProxy, {
      upstream: this.config.API_URL,
      prefix: '/socket.io',
      rewritePrefix: '/socket.io',
      websocket: true,
    })

    app.register(authPlugin, { required: false })
    app.register(refreshPlugin, { apiUrl: this.config.API_URL })

    const logger = app.log

    const middlewaresFactory = new MiddlewaresFactory(this.config);
    await middlewaresFactory.apply(app);

    const ssrFactory = new SsrFactory(this.config, logger);
    await ssrFactory.setup(app);

    if (isProd) {
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
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          return reply.status(404).send('Not Found');
        }

        if (req.url.startsWith('/api/')) {
          return reply.status(404).send({ ok: false, error: 'Not Found' });
        }

        return ssrHandler(req, reply);
      });
    } else {
      app.get('*', ssrFactory.getHandler());
    }

    return app;
  }
}
