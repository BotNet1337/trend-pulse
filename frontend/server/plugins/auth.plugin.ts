import type { FastifyPluginAsync, FastifyRequest } from 'fastify'
import fp from 'fastify-plugin'
import { jwtDecode } from 'jwt-decode'
import { z } from 'zod'
import { jwtUserSchema, type JwtUser } from '../../src/entities/user/model'

/**
 * Field whitelist for the user payload exposed on `request.user` and
 * embedded into `__INITIAL_STATE__`. Mirrors `JwtUserSchema` but stays
 * permissive on extra JWT claims so that decoding does not fail outright —
 * only the whitelisted fields are forwarded.
 *
 * SECURITY (TASK-AUDIT-RELEASE-1 / C7):
 * Previously this used `[key: string]: unknown`, which forwarded the full
 * JWT (including `iat`, `exp`, `jti`, and any future claims) to the browser.
 * Now we Zod-pick the safe subset and drop the rest before storing.
 */
export type AuthUserPayload = JwtUser

declare module 'fastify' {
  interface FastifyRequest {
    user?: AuthUserPayload | null
  }
}

export interface AuthPluginOptions {
  required?: boolean
  getToken?: (req: FastifyRequest) => string | null
}

const decodedTokenSchema = z
  .object({
    exp: z.number().optional(),
    iat: z.number().optional(),
  })
  .passthrough()

const isTokenExpired = (exp: number | undefined): boolean => {
  if (typeof exp !== 'number') return false
  // `exp` is unix seconds; allow a small clock-skew window so we don't bounce
  // a request that arrived right at the boundary.
  const SKEW_SEC = 5
  return exp + SKEW_SEC < Math.floor(Date.now() / 1000)
}

const authPlugin: FastifyPluginAsync<AuthPluginOptions> = async (fastify, opts) => {
  fastify.decorateRequest('authUser', null)

  fastify.addHook('onRequest', async (request) => {
    const token = (opts.getToken ?? defaultGetToken)(request)

    if (!token) {
      return
    }

    try {
      const decoded = decodedTokenSchema.parse(jwtDecode(token))
      // Treat an expired JWT as anonymous. Without this, SSR keeps reading
      // the stale cookie, the anonymous layout sees a "user" and redirects
      // back to /workspaces, where the next API call 401s — producing a
      // sign-in ↔ workspaces redirect loop in the browser.
      if (isTokenExpired(decoded.exp)) {
        request.user = null
        return
      }

      const userParse = jwtUserSchema.safeParse(decoded)
      request.user = userParse.success ? userParse.data : null
    } catch {
      request.user = null
    }
  })
}

function defaultGetToken(req: FastifyRequest): string | null {
  const header = req.headers['authorization']
  if (header && typeof header === 'string') {
    const [scheme, token] = header.split(' ')
    if (scheme === 'Bearer' && token) {
      return token
    }
  }

  const cookieToken = req.cookies?.access_token

  if (cookieToken) {
    return cookieToken
  }

  return null
}

export default fp(authPlugin, {
  name: 'auth-plugin',
})
