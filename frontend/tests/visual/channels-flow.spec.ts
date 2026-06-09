import { test, expect } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"
import {
  channelFactory,
  mockChannelsList,
  mockOAuthInitiate,
  mockOAuthPopup,
  mockWorkspace,
} from "./fixtures/channels"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping channels flow specs.",
  )
}

const WORKSPACE_ID = "44444444-4444-4444-8444-444444444444"

const setupChannelsPage = async (
  page: import("@playwright/test").Page,
  channels: ReturnType<typeof channelFactory>[],
) => {
  await mockOAuthPopup(page)
  await mockWorkspace(page, WORKSPACE_ID)
  const list = await mockChannelsList(page, WORKSPACE_ID, channels)
  await mockOAuthInitiate(page, WORKSPACE_ID)
  return list
}

test.describe("channels · empty state", () => {
  test("first-time workspace shows inline platform tiles and a Connect dialog with a 2x2 grid", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await setupChannelsPage(page, [])

    await page.goto(`/workspaces/${WORKSPACE_ID}/channels`)
    await expect(page.getByRole("heading", { name: "Channels" })).toBeVisible()

    // Empty state has 4 inline platform tiles (no modal).
    const inlineTiles = page.locator(
      '[data-testid^="platform-tile-"]',
    )
    await expect(inlineTiles).toHaveCount(4)
  })
})

test.describe("channels · connect dialog", () => {
  test("dialog opens, platform select updates the Continue label, click triggers OAuth popup", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await setupChannelsPage(page, [
      channelFactory({ workspaceId: WORKSPACE_ID, id: "seed-card", name: "@seed" }),
    ])

    await page.goto(`/workspaces/${WORKSPACE_ID}/channels`)
    await page.getByRole("button", { name: "Connect channel" }).click()

    const grid = page.getByTestId("connect-channel-platform-grid")
    await expect(grid).toBeVisible()
    await expect(grid.locator('[data-testid^="platform-tile-"]')).toHaveCount(4)

    const continueBtn = page.getByTestId("connect-channel-continue")
    await expect(continueBtn).toBeDisabled()

    await page.getByTestId("platform-tile-instagram").click()
    await expect(continueBtn).toContainText("Continue with Instagram")
    await expect(continueBtn).toBeEnabled()

    await continueBtn.click()

    // Assert the popup helper was invoked with the provider URL.
    const popupCalls = await page.evaluate(
      () => (window as unknown as { __oauthPopupCalls: unknown[] }).__oauthPopupCalls,
    )
    expect(popupCalls.length).toBeGreaterThanOrEqual(1)
    const first = popupCalls[0] as { url: string; features: string }
    expect(first.url).toContain("/oauth/instagram")
    expect(first.features).toContain("width=600")
  })
})

// Realtime WS highlight is exercised in backend integration tests
// (`channel-events.listener.spec.ts`). End-to-end exercise across a real
// socket.io upgrade from a Playwright browser is deferred — running a real
// gateway with a stubbed channels REST refetch needs more plumbing than the
// other specs and adds little signal beyond the listener unit test.

test.describe("channels · disconnect", () => {
  test("disconnect modal removes the card after confirmation", async ({
    page,
  }) => {
    skipUnlessSignedIn()

    const target = channelFactory({
      workspaceId: WORKSPACE_ID,
      id: "card-target",
      name: "@target",
      subject: "ig:target",
    })
    const list = await setupChannelsPage(page, [target])

    await page.route(
      `**/api/workspaces/${WORKSPACE_ID}/channels/${target.id}`,
      async (route) => {
        if (route.request().method() === "DELETE") {
          await route.fulfill({ status: 200, body: "" })
        } else {
          await route.fallback()
        }
      },
    )

    await page.goto(`/workspaces/${WORKSPACE_ID}/channels`)
    await expect(page.locator('[data-testid="channel-card"]')).toHaveCount(1)

    await page.getByRole("button", { name: "Channel actions" }).click()
    await page.getByRole("menuitem", { name: "Disconnect" }).click()

    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    list.setChannels([])
    await dialog.getByRole("button", { name: "Disconnect channel" }).click()

    await expect(page.locator('[data-testid="channel-card"]')).toHaveCount(0)
  })
})

test.describe("channels · popup callback pages", () => {
  test("/connected page renders the success card", async ({ page }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    await mockChannelsList(page, WORKSPACE_ID, [])

    await page.goto(
      `/workspaces/${WORKSPACE_ID}/channels/11111111-1111-4111-8111-111111111111/connected`,
    )
    await expect(page.getByTestId("channel-connected-popup")).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Channel connected" }),
    ).toBeVisible()
  })

  test("/connect-failed page surfaces the reason and platform", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID)
    await mockChannelsList(page, WORKSPACE_ID, [])

    await page.goto(
      `/channels/connect-failed?reason=invalid_state&platform=instagram`,
    )
    await expect(page.getByTestId("channel-connect-failed-popup")).toBeVisible()
    await expect(page.getByText("Couldn't connect channel")).toBeVisible()
    await expect(page.getByText("Invalid state")).toBeVisible()
    await expect(page.getByText("instagram", { exact: false })).toBeVisible()
  })
})
