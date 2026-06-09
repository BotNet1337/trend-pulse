import type { FastifyPluginAsync } from 'fastify'
import fp from 'fastify-plugin'
import type { JwtUser } from '../../src/entities/user/model'

/**
 * Auth plugin — decorates `request.user` for downstream consumers.
 *
 * TrendPulse uses fastapi-users **httpOnly cookie** transport (`fastapiusersauth`).
 * The cookie is opaque to the SSR layer — we do NOT decode its JWT claims here
 * because:
 *   (a) the cookie name is `fastapiusersauth` (not `access_token`), and
 *   (b) the JWT only carries `sub`/`aud`/`exp` — user data (email, plan) is NOT
 *       in the JWT and must be fetched from `GET /users/me`.
 *
 * User resolution happens in the SSR prefetch layer (`prefetch/fetchers.ts` →
 * `fetchCurrentUser`), which forwards the inbound `Cookie` header to the
 * upstream API and returns the UserMeResponse. The result is stored in
 * `__INITIAL_STATE__.queries` (key: `['viewer', 'me']`) for client hydration.
 *
 * This plugin now acts purely as a no-op type decorator so that all
 * `request.user` references in the codebase continue to compile without
 * removing the FastifyRequest augmentation.
 */
export type AuthUserPayload = JwtUser

declare module 'fastify' {
  interface FastifyRequest {
    user?: AuthUserPayload | null
  }
}

export interface AuthPluginOptions {
  required?: boolean
}

const authPlugin: FastifyPluginAsync<AuthPluginOptions> = async (fastify) => {
  fastify.decorateRequest('user', null)
}

export default fp(authPlugin, {
  name: 'auth-plugin',
})
