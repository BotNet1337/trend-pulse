import { test, expect, type Page } from "@playwright/test"

import { requireTestCredentials } from "./fixtures/auth"
import { channelFactory, mockChannelsList, mockWorkspace } from "./fixtures/channels"
import {
  dashboardFixture,
  emptyDashboardFixture,
  mockDashboard,
} from "./fixtures/analytics"

const skipUnlessSignedIn = () => {
  const creds = requireTestCredentials()
  test.skip(
    !creds,
    "TEST_EMAIL / TEST_PASSWORD not set — skipping analytics flow specs.",
  )
}

const WORKSPACE_ID = "55555555-5555-4555-8555-555555555555"
const CHANNEL_ID = "66666666-6666-4666-8666-666666666666"

const setupDashboard = async (page: Page) => {
  await mockWorkspace(page, WORKSPACE_ID, { channelsCount: 5, postsCount: 128 })
  await mockChannelsList(page, WORKSPACE_ID, [
    channelFactory({
      workspaceId: WORKSPACE_ID,
      id: CHANNEL_ID,
      platform: "instagram",
      name: "@acme",
      meta: { displayName: "Acme IG" },
    }),
  ])
  const dashboard = await mockDashboard(
    page,
    WORKSPACE_ID,
    dashboardFixture(WORKSPACE_ID, CHANNEL_ID),
  )
  return dashboard
}

test.describe("dashboard · loaded", () => {
  test("renders all 4 metrics by the active workspace", async ({ page }) => {
    skipUnlessSignedIn()
    await setupDashboard(page)

    await page.goto(`/workspaces/${WORKSPACE_ID}/dashboard`)

    await expect(page.getByRole("heading", { name: "Дашборд" })).toBeVisible()
    // KPI cards
    await expect(page.getByTestId("kpi-totalPosts")).toBeVisible()
    await expect(page.getByTestId("kpi-activeChannels")).toBeVisible()
    await expect(page.getByTestId("kpi-upcomingPublications")).toBeVisible()
    // by-status line chart
    await expect(page.getByTestId("publications-chart")).toBeVisible()
    // success-rate gauge
    await expect(page.getByTestId("success-rate-gauge")).toBeVisible()
    await expect(page.getByText("94%")).toBeVisible()
    // platform breakdown — channel name resolved from the channels list
    await expect(page.getByTestId("platform-breakdown")).toBeVisible()
    await expect(page.getByText("Acme IG")).toBeVisible()
  })

  test("nav has Dashboard as the first workspace entry", async ({ page }) => {
    skipUnlessSignedIn()
    await setupDashboard(page)

    await page.goto(`/workspaces/${WORKSPACE_ID}/dashboard`)
    const nav = page.locator("aside nav")
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible()
  })
})

test.describe("dashboard · date-range", () => {
  test("changing the preset refetches with a new range", async ({ page }) => {
    skipUnlessSignedIn()
    const dashboard = await setupDashboard(page)

    await page.goto(`/workspaces/${WORKSPACE_ID}/dashboard`)
    await expect(page.getByTestId("publications-chart")).toBeVisible()

    const before = dashboard.count()
    const beforeRange = dashboard.lastRange()

    await page.getByTestId("date-preset-7d").click()

    await expect
      .poll(() => dashboard.count(), { timeout: 5_000 })
      .toBeGreaterThan(before)
    // The new request carries a different (narrower) `from` bound.
    await expect
      .poll(() => dashboard.lastRange().from)
      .not.toBe(beforeRange.from)
  })
})

test.describe("dashboard · empty state", () => {
  test("new workspace with no data shows onboarding", async ({ page }) => {
    skipUnlessSignedIn()
    await mockWorkspace(page, WORKSPACE_ID, { channelsCount: 0, postsCount: 0 })
    await mockChannelsList(page, WORKSPACE_ID, [])
    await mockDashboard(page, WORKSPACE_ID, emptyDashboardFixture(WORKSPACE_ID))

    await page.goto(`/workspaces/${WORKSPACE_ID}/dashboard`)

    await expect(page.getByTestId("dashboard-empty")).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Подключить канал" }),
    ).toBeVisible()
  })
})

test.describe("dashboard · error state", () => {
  test("a failed request shows the error state, not a blank screen", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    const dashboard = await setupDashboard(page)
    dashboard.setError(true)

    await page.goto(`/workspaces/${WORKSPACE_ID}/dashboard`)

    await expect(page.getByTestId("dashboard-error")).toBeVisible()
    await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible()
  })
})

test.describe("dashboard · degraded metric", () => {
  test("a degraded metric shows a soft tile, others still render", async ({
    page,
  }) => {
    skipUnlessSignedIn()
    const dashboard = await setupDashboard(page)
    const payload = dashboardFixture(WORKSPACE_ID, CHANNEL_ID)
    const kpi = payload.metrics.find((m) => m.slug === "kpi-cards")
    if (kpi) {
      kpi.degraded = true
      kpi.rows = []
    }
    dashboard.setDashboard(payload)

    await page.goto(`/workspaces/${WORKSPACE_ID}/dashboard`)

    await expect(page.getByTestId("metric-degraded")).toBeVisible()
    // Other tiles keep rendering normally.
    await expect(page.getByTestId("publications-chart")).toBeVisible()
  })
})
