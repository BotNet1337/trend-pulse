import { z } from "zod"
import type { components } from "@/shared/api/gen.types"

/**
 * User entity from TrendPulse OpenAPI (UserRead schema).
 * Maps to the fastapi-users UserRead response model.
 */
export type User = components["schemas"]["UserRead"]

/**
 * Schema for the JWT-derived user payload exposed to the SSR layer and the
 * browser via `__INITIAL_STATE__`.
 *
 * SECURITY: Whitelist of fields safe to expose to the browser.
 * Never add a field here that the user shouldn't see in View Source.
 */
export const jwtUserSchema = z.object({
  userId: z.string().min(1),
  accountId: z.string().min(1),
  email: z.string().email().optional(),
  provider: z.string().min(1),
})

/**
 * Decoded JWT payload safe to expose to client-side code.
 */
export type JwtUser = z.infer<typeof jwtUserSchema>
