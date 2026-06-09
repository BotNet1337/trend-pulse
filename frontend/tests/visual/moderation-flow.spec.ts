import { test, expect } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"
import {
  grantModeratePermission,
  mockModerationApi,
  moderationItemFactory,
} from "./fixtures/moderation"

/**
 * Moderation admin flow (TASK-072). The moderation API (TASK-071) and the
 * permission concept (TASK-069/070) are NOT merged yet, so these specs mock the
 * `/moderation/*` endpoints (project network-mock convention, see channels
 * fixture) and inject the `ModerateContent` permission via `__INITIAL_STATE__`.
 *
 * Live integration is pending app#43–45 (moderation backend) + 069/070
 * (permissions) merging — once live, drop `grantModeratePermission` + the API
 * mocks and point these at the real endpoints.
 */
const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping moderation flow specs.",
  )
}

test.describe("moderation · navigation gating", () => {
  test("non-admin does NOT see the Moderate nav item", async ({ page }) => {
    skipUnlessSignedIn()
    // No permission granted → the admin nav group must not render.
    await page.goto("/workspaces")
    await expect(page.getByTestId("nav-moderate")).toHaveCount(0)
  })

  test("admin sees the Moderate nav item", async ({ page }) => {
    skipUnlessSignedIn()
    await grantModeratePermission(page)
    await mockModerationApi(page, [moderationItemFactory({ id: "req-1" })])

    await page.goto("/moderation")
    await expect(
      page.getByRole("heading", { name: "На модерации" }),
    ).toBeVisible()
  })
})

test.describe("moderation · queue", () => {
  test("renders the pending queue with cards", async ({ page }) => {
    skipUnlessSignedIn()
    await grantModeratePermission(page)
    await mockModerationApi(page, [
      moderationItemFactory({ id: "req-1" }),
      moderationItemFactory({ id: "req-2" }),
    ])

    await page.goto("/moderation")
    await expect(page.getByTestId("moderation-card")).toHaveCount(2)
  })

  test("empty queue shows the empty state", async ({ page }) => {
    skipUnlessSignedIn()
    await grantModeratePermission(page)
    await mockModerationApi(page, [])

    await page.goto("/moderation")
    await expect(page.getByTestId("moderation-empty")).toBeVisible()
  })
})

test.describe("moderation · approve", () => {
  test("approving removes the card from the queue", async ({ page }) => {
    skipUnlessSignedIn()
    await grantModeratePermission(page)
    const api = await mockModerationApi(page, [
      moderationItemFactory({ id: "req-1" }),
    ])

    await page.goto("/moderation")
    await page.getByTestId("moderation-card-approve").click()
    await page.getByTestId("approve-confirm").click()

    await expect(page.getByTestId("moderation-card")).toHaveCount(0)
    expect(api.approvedIds).toContain("req-1")
  })
})

test.describe("moderation · reject", () => {
  test("reject requires a reason — submit gated until non-empty", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await grantModeratePermission(page)
    await mockModerationApi(page, [moderationItemFactory({ id: "req-1" })])

    await page.goto("/moderation")
    await page.getByTestId("moderation-card-reject").click()

    const confirm = page.getByTestId("reject-confirm")
    await expect(confirm).toBeDisabled()

    await page.getByTestId("reject-reason").fill("Нарушает правила площадки")
    await expect(confirm).toBeEnabled()
  })

  test("rejecting with a reason removes the card and sends the reason", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    await grantModeratePermission(page)
    const api = await mockModerationApi(page, [
      moderationItemFactory({ id: "req-1" }),
    ])

    await page.goto("/moderation")
    await page.getByTestId("moderation-card-reject").click()
    await page.getByTestId("reject-reason").fill("Спам")
    await page.getByTestId("reject-confirm").click()

    await expect(page.getByTestId("moderation-card")).toHaveCount(0)
    expect(api.rejected).toEqual([{ id: "req-1", reason: "Спам" }])
  })
})
