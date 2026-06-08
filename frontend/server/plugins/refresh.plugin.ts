import type { FastifyPluginAsync } from 'fastify'
import fp from 'fastify-plugin'

/**
 * Server-side refresh endpoint that lives outside the `/api` proxy. The
 * client's axios interceptor calls `POST /__auth/refresh` when it sees a
 * 401, this plugin reads the `refresh_token` cookie, forwards it to the
 * backend's `/auth/token/refresh` route and pipes the resulting `Set-Cookie`
 * headers back to the browser.
 *
 * Why a separate plugin and not the existing `/api` proxy:
 *   - Single, well-known refresh path makes it possible to scope the
 *     `refresh_token` cookie to it later (path-restricted cookies).
 *   - Easier to bolt on CSRF protection / origin allow-listing in one place.
 *   - The client never needs the refresh JWT in JS land — the token is
 *     read from the httpOnly cookie server-side, the upstream reply is
 *     consumed and discarded server-side too.
 */
export interface RefreshPluginOptions {
  apiUrl: string
}

const refreshPlugin: FastifyPluginAsync<RefreshPluginOptions> = async (
  fastify,
  opts,
) => {
  const upstreamUrl = `${opts.apiUrl.replace(/\/$/, '')}/auth/token/refresh`

  fastify.post('/__auth/refresh', async (request, reply) => {
    const refreshToken = request.cookies?.refresh_token
    const accessToken = request.cookies?.access_token

    if (!refreshToken && !accessToken) {
      reply.code(401).send({ message: 'No refresh token cookie present' })
      return
    }

    const upstreamHeaders: Record<string, string> = {
      authorization: `Bearer ${refreshToken ?? accessToken}`,
      // The upstream Nest controller is JSON-only and rejects unrecognised
      // content types — pin it explicitly even though the body is empty.
      'content-type': 'application/json',
      accept: 'application/json',
    }

    let upstream: Response
    try {
      upstream = await fetch(upstreamUrl, {
        method: 'POST',
        headers: upstreamHeaders,
        body: '{}',
      })
    } catch (err) {
      request.log.warn({ err }, 'refresh upstream fetch failed')
      reply.code(502).send({ message: 'Refresh upstream unreachable' })
      return
    }

    // Mirror Set-Cookie from upstream — the AuthCookiesInterceptor sets both
    // `access_token` and `refresh_token` here, with the right secure / httpOnly
    // / persist flags already applied by the backend interceptor. Forward each
    // entry verbatim instead of re-parsing them on this hop.
    const setCookieHeaders = upstream.headers.getSetCookie?.() ?? []
    for (const cookie of setCookieHeaders) {
      reply.header('set-cookie', cookie)
    }

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => '')
      reply.code(upstream.status).send(text || { message: 'Refresh failed' })
      return
    }

    reply.code(204).send()
  })
}

export default fp(refreshPlugin, {
  name: 'refresh-plugin',
  dependencies: ['@fastify/cookie'],
})
