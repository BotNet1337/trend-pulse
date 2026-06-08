import { test, expect } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping live auth specs.",
  )
  return creds
}

test.describe("auth · sign-in", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("fresh sign-in via API gets a session that loads /workspaces", async ({
    page,
  }) => {
    const creds = skipUnlessSignedIn()
    if (!creds) return
    await signInViaApi(page, creds)
    await page.goto("/workspaces")
    await page.waitForSelector('[data-testid="create-workspace-card"], [data-testid="workspace-card"]', {
      timeout: 10_000,
    })
    expect(page.url()).toContain("/workspaces")
  })
})

test.describe("auth · refresh token", () => {
  test("expired access cookie triggers axios interceptor refresh", async ({
    page,
    context,
  }) => {
    skipUnlessSignedIn()

    // Land on a page that has the React app already running.
    await page.goto("/workspaces")
    await page.waitForSelector(
      '[data-testid="create-workspace-card"], [data-testid="workspace-card"]',
      { timeout: 10_000 },
    )

    const before = await context.cookies()
    const accessCookie = before.find((c) => c.name === "access_token")
    expect(accessCookie, "expected access_token cookie after sign-in").toBeTruthy()
    expect(
      before.find((c) => c.name === "refresh_token"),
      "expected refresh_token cookie after sign-in",
    ).toBeTruthy()

    // Replace the access cookie with a definitely-invalid JWT so the proxy
    // forwards a guaranteed 401 to the backend on the next API call.
    if (accessCookie) {
      await context.clearCookies({ name: "access_token" })
      await context.addCookies([
        {
          ...accessCookie,
          value: "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjF9.deadbeef",
        },
      ])
    }

    // Capture every request so we can assert the interceptor reached the
    // refresh endpoint after the 401 — independent of whether the backend
    // accepts the refresh in this fixture environment.
    const refreshRequests: string[] = []
    page.on("request", (req) => {
      if (req.url().includes("/auth/token/refresh")) {
        refreshRequests.push(req.method())
      }
    })

    // Provoke an XHR through `apiClient` so the response interceptor handles
    // the 401. The dev-exposed handle lives at window.__DEV_API_CLIENT__.
    await page.evaluate(async () => {
      const client = (window as unknown as {
        __DEV_API_CLIENT__?: {
          get: (
            url: string,
            options: { params: Record<string, unknown> },
          ) => Promise<{ status: number }>
        }
      }).__DEV_API_CLIENT__
      if (!client) return
      try {
        await client.get("/workspaces", {
          params: { offset: 0, limit: 1, withArchived: false },
        })
      } catch {
        // Swallow — the assertion is on whether the refresh hop happened,
        // not on the final state (the backend may reject our synthetic
        // expired-JWT scenario in a way the interceptor can't recover from).
      }
    })

    // Allow the interceptor to fire its refresh request.
    await page.waitForTimeout(2000)

    expect(
      refreshRequests,
      "interceptor must POST /auth/token/refresh on 401",
    ).toContain("POST")
  })
})
