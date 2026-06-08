import { z } from "zod"
import type { MediaObject } from "@/entities/media"

/**
 * User entity. The backend doesn't currently surface `UserDto` as a named
 * OpenAPI component (no `@ApiResponse({ type: UserDto })` decorator on the
 * users controller), so this is a literal mirror of the documented contract.
 * Once the decorator is wired, swap to
 * `components["schemas"]["UserResponseDto"]`.
 */
export interface User {
  id: string
  name: string | null
  avatar: MediaObject | null
  createdAt: string
  updatedAt: string
}

/**
 * Schema for the JWT-derived user payload exposed to the SSR layer and the
 * browser via `__INITIAL_STATE__`.
 *
 * SECURITY (TASK-AUDIT-RELEASE-1 / C7):
 * Whitelist of fields safe to expose to the browser. Anything else in the
 * raw JWT (`iat`, `exp`, `jti`, internal claims, future role/billing fields)
 * is dropped. NEVER add a field here that the user shouldn't see in
 * `View Source`.
 */
export const jwtUserSchema = z.object({
  userId: z.string().min(1),
  accountId: z.string().min(1),
  email: z.string().email().optional(),
  provider: z.string().min(1),
})

/**
 * Decoded JWT payload safe to expose to client-side code. Field names mirror
 * the `userId` / `accountId` keys signed by `IAM` — frontend MUST use those
 * names verbatim, otherwise downstream calls (presign metadata, ownership
 * checks) silently send empty strings and the backend rejects with
 * "Invalid uuid".
 */
export type JwtUser = z.infer<typeof jwtUserSchema>
