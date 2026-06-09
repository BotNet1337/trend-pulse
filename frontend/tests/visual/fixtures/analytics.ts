import type { Page, Route } from "@playwright/test"

import type { MockChannel } from "./channels"

export interface MockMetricResult {
  slug: string
  title: string
  resultShape: string
  degraded: boolean
  rows: Array<Record<string, string | number | boolean | null>>
}

export interface MockDashboard {
  workspaceId: string
  degraded: boolean
  metrics: MockMetricResult[]
}

/**
 * A representative, fully-populated dashboard payload — mirrors the TASK-075
 * envelope 1:1 (slugs, snake_case columns, `success_rate` 0..1, breakdown
 * `channel_id` UUID). Lets the e2e exercise all 4 tiles without the (unmerged)
 * analytics backend.
 */
export const dashboardFixture = (
  workspaceId: string,
  channelId: string,
): MockDashboard => ({
  workspaceId,
  degraded: false,
  metrics: [
    {
      slug: "kpi-cards",
      title: "KPI cards",
      resultShape: "kpi",
      degraded: false,
      rows: [{ total_posts: 128, active_channels: 5, upcoming_publications: 14 }],
    },
    {
      slug: "publications-by-status-over-time",
      title: "Publications by status over time",
      resultShape: "timeseries",
      degraded: false,
      rows: [
        { day: "2026-05-09", status: "published", total: 12 },
        { day: "2026-05-10", status: "published", total: 18 },
        { day: "2026-05-09", status: "failed", total: 2 },
        { day: "2026-05-10", status: "scheduled", total: 6 },
      ],
    },
    {
      slug: "publish-success-rate",
      title: "Publish success rate",
      resultShape: "scalar",
      degraded: false,
      rows: [{ published: 241, failed: 15, total: 256, success_rate: 0.94 }],
    },
    {
      slug: "platform-channel-breakdown",
      title: "Platform / channel breakdown",
      resultShape: "breakdown",
      degraded: false,
      rows: [{ platform: "instagram", channel_id: channelId, total: 86 }],
    },
  ],
})

/** All metrics empty (new workspace → empty state). */
export const emptyDashboardFixture = (workspaceId: string): MockDashboard => ({
  workspaceId,
  degraded: false,
  metrics: [
    { slug: "kpi-cards", title: "KPI cards", resultShape: "kpi", degraded: false, rows: [] },
    {
      slug: "publications-by-status-over-time",
      title: "Publications by status over time",
      resultShape: "timeseries",
      degraded: false,
      rows: [],
    },
    {
      slug: "publish-success-rate",
      title: "Publish success rate",
      resultShape: "scalar",
      degraded: false,
      rows: [],
    },
    {
      slug: "platform-channel-breakdown",
      title: "Platform / channel breakdown",
      resultShape: "breakdown",
      degraded: false,
      rows: [],
    },
  ],
})

export interface MockDashboardHandle {
  /** Number of dashboard requests served so far. */
  count: () => number
  /** Most recent `from`/`to` query the page sent. */
  lastRange: () => { from: string | null; to: string | null }
  /** Swap the payload returned by subsequent requests. */
  setDashboard: (next: MockDashboard) => void
  /** Make subsequent requests fail with a 500 (hard error state). */
  setError: (enabled: boolean) => void
}

/**
 * Mocks the analytics dashboard endpoint. Network-layer stub because the
 * backend (TASK-075 / app#46) isn't merged yet — once it is, point the e2e at
 * the live endpoint and drop this stub. Tracks call count + last range so the
 * spec can assert a date-range change triggered a refetch.
 */
export const mockDashboard = async (
  page: Page,
  workspaceId: string,
  initial: MockDashboard,
): Promise<MockDashboardHandle> => {
  let current = initial
  let error = false
  let calls = 0
  let last: { from: string | null; to: string | null } = { from: null, to: null }

  await page.route(
    `**/api/workspaces/${workspaceId}/analytics/dashboard**`,
    async (route: Route) => {
      calls += 1
      const url = new URL(route.request().url())
      last = { from: url.searchParams.get("from"), to: url.searchParams.get("to") }
      if (error) {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ message: "ClickHouse unavailable", code: 50000 }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current),
      })
    },
  )

  return {
    count: () => calls,
    lastRange: () => last,
    setDashboard: (next) => {
      current = next
    },
    setError: (enabled) => {
      error = enabled
    },
  }
}

export type { MockChannel }
