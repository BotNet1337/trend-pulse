import { expect, test } from "@playwright/test"

import { requireTestCredentials, signInViaApi } from "./fixtures/auth"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping SSR hydration specs.",
  )
  return creds
}

test.describe("SSR data hydration (TASK-036)", () => {
  test("HTML payload contains a non-empty __INITIAL_STATE__.queries on /workspaces", async ({
    page,
  }) => {
    skipUnlessSignedIn()

    const response = await page.goto("/workspaces")
    expect(response?.ok(), "expected SSR response").toBeTruthy()

    const html = (await response?.text()) ?? ""
    expect(html).toMatch(/window\.__INITIAL_STATE__\s*=/)

    const match = html.match(
      /window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\})\s*<\/script>/,
    )
    expect(match, "expected an inline initial-state script").toBeTruthy()

    const state = JSON.parse(match![1]) as {
      user: unknown
      queries?: Array<{ key: unknown[]; data: unknown }>
    }

    expect(state.queries, "queries array should be present").toBeInstanceOf(Array)
    expect(state.queries!.length, "expected at least one prefetched query").toBeGreaterThan(0)
  })

  test("workspace cards render in raw HTML (works without JS)", async ({
    browser,
  }) => {
    const creds = skipUnlessSignedIn()
    if (!creds) return

    const ctxWithJs = await browser.newContext({ ignoreHTTPSErrors: true })
    const setupPage = await ctxWithJs.newPage()
    await signInViaApi(setupPage, creds)
    const cookies = await ctxWithJs.cookies()
    await ctxWithJs.close()

    const noJsCtx = await browser.newContext({
      ignoreHTTPSErrors: true,
      javaScriptEnabled: false,
    })
    await noJsCtx.addCookies(cookies)
    const page = await noJsCtx.newPage()

    const response = await page.goto("/workspaces")
    expect(response?.status()).toBeLessThan(400)

    const html = await response!.text()

    // The card list is identifiable via data-testid attributes injected by the
    // workspace list component. SSR must include them in the served HTML for
    // the no-JS test to pass — this is the smoke signal that hydration data
    // reached the renderer (not just the inline script).
    const hasWorkspaceCard = /data-testid=["']workspace-card["']/.test(html)
    const hasCreateCard = /data-testid=["']create-workspace-card["']/.test(html)
    expect(
      hasWorkspaceCard || hasCreateCard,
      "expected at least one workspace card or the create card in raw HTML",
    ).toBe(true)

    await noJsCtx.close()
  })
})
