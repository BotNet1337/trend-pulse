import type { APIRequestContext, Page } from "@playwright/test"

export interface SignInOptions {
  email: string
  password: string
}

const isPage = (value: Page | APIRequestContext): value is Page =>
  typeof (value as Page).goto === "function"

/**
 * Performs a programmatic sign-in flow against the live backend so the
 * resulting cookie session is reused across visual specs. Reads credentials
 * from `TEST_EMAIL` / `TEST_PASSWORD` env vars; tests using this should
 * `test.skip` if either is missing.
 */
export const signInViaApi = async (
  target: Page | APIRequestContext,
  { email, password }: SignInOptions,
): Promise<void> => {
  const requestCtx = isPage(target) ? target.request : target
  const response = await requestCtx.post("/api/auth/email/sign-in", {
    data: { email, password },
  })
  if (!response.ok()) {
    throw new Error(
      `sign-in failed: ${response.status()} ${await response.text()}`,
    )
  }
}

export const requireTestCredentials = (): SignInOptions | null => {
  const email = process.env.TEST_EMAIL?.trim()
  const password = process.env.TEST_PASSWORD
  if (!email || !password) return null
  return { email, password }
}
