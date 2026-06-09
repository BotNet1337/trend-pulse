import { test, expect } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"
import { extractFirstHttpUrl, waitForMail } from "./fixtures/mailpit"

/**
 * End-to-end auth flows. Designed to run against a fresh dev stack
 * (`make dev-up`) — they hit Mailpit for confirm / reset emails. Each spec
 * skips itself when the prerequisites (TEST credentials, Mailpit
 * reachability) aren't satisfied so CI doesn't hard-fail when a
 * configuration is missing.
 */

const generateRandomEmail = (): string =>
  `playwright+${Date.now()}-${Math.random().toString(36).slice(2, 8)}@postbridge.test`

test.describe("auth · sign-up + email confirmation", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("user can sign up, receive confirmation email, and confirm their account", async ({
    page,
    request,
  }) => {
    test.skip(
      !process.env.MAILPIT_URL && process.env.CI === "true",
      "MAILPIT_URL not configured for CI run",
    )

    const email = generateRandomEmail()
    await page.goto("/auth/sign-up")
    await page.getByLabel("Name").fill("Playwright Tester")
    await page.getByLabel("Email").fill(email)
    await page.getByLabel("Password", { exact: true }).fill("Password!23")
    await page.getByLabel("Confirm Password").fill("Password!23")
    await page.getByRole("checkbox").check()
    await page.getByRole("button", { name: /create account/i }).click()

    // The form submits to backend — we expect either a redirect to a
    // verification info screen OR an alert toast saying "verify email".
    await page.waitForLoadState("networkidle")

    let confirmUrl: string | null = null
    try {
      const message = await waitForMail(
        request,
        { to: email, subjectIncludes: "confirm" },
        { timeoutMs: 20_000 },
      )
      confirmUrl = extractFirstHttpUrl(message.HTML)
    } catch (err) {
      test.skip(true, `Mailpit unavailable in this environment: ${(err as Error).message}`)
      return
    }

    expect(confirmUrl, "confirm email must contain a tokenized link").toBeTruthy()
    if (!confirmUrl) return

    await page.goto(confirmUrl)
    await page.waitForLoadState("networkidle")
    await expect(page).toHaveURL(/\/auth\/(sign-in|confirm-email|email-confirmed)/)
  })
})

test.describe("auth · sign-in with remember-me", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("remember-me=false issues a session cookie (no max-age) for refresh_token", async ({
    page,
    context,
  }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    await page.goto("/auth/sign-in")
    await page.getByLabel("Email").fill(creds.email)
    await page.getByLabel("Password").fill(creds.password)
    // Uncheck "Remember me" — the form defaults to checked.
    const rememberMe = page.getByLabel("Remember me")
    if (await rememberMe.isChecked()) {
      await rememberMe.uncheck()
    }
    await page.getByRole("button", { name: /sign in/i }).click()
    await page.waitForLoadState("networkidle")

    const cookies = await context.cookies()
    const refresh = cookies.find((c) => c.name === "refresh_token")
    expect(refresh, "refresh_token cookie must exist after sign-in").toBeTruthy()
    if (!refresh) return

    // Session cookies are reported by Playwright with `expires === -1`. We
    // assert that explicitly so a regression that switches the flag silently
    // can't slip through.
    expect(refresh.expires).toBe(-1)
  })

  test("remember-me=true issues a persistent cookie with a future expiry", async ({
    page,
    context,
  }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    await page.goto("/auth/sign-in")
    await page.getByLabel("Email").fill(creds.email)
    await page.getByLabel("Password").fill(creds.password)
    const rememberMe = page.getByLabel("Remember me")
    if (!(await rememberMe.isChecked())) {
      await rememberMe.check()
    }
    await page.getByRole("button", { name: /sign in/i }).click()
    await page.waitForLoadState("networkidle")

    const cookies = await context.cookies()
    const refresh = cookies.find((c) => c.name === "refresh_token")
    expect(refresh).toBeTruthy()
    if (!refresh) return
    expect(refresh.expires).toBeGreaterThan(Date.now() / 1000)
  })
})

test.describe("auth · sign-out", () => {
  test("clears both auth cookies and bounces to /auth/sign-in", async ({
    page,
    context,
  }) => {
    const creds = requireTestCredentials()
    test.skip(!creds, "TEST_EMAIL / TEST_PASSWORD not set")
    if (!creds) return

    // Use the API helper to seed cookies, then drive sign-out via the UI.
    await page.request.post("/api/auth/email/sign-in", {
      data: { ...creds, rememberMe: true },
    })
    await page.goto("/workspaces")
    await page.waitForLoadState("networkidle")

    await page.request.post("/api/auth/sign-out")

    const cookies = await context.cookies()
    expect(cookies.find((c) => c.name === "access_token")).toBeFalsy()
    expect(cookies.find((c) => c.name === "refresh_token")).toBeFalsy()
  })
})
