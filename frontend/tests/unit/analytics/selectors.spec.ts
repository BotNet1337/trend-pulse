import { describe, expect, it } from "vitest"

import {
  isDashboardEmpty,
  isMetricDegraded,
  METRIC_SLUGS,
  selectKpi,
  selectPlatformBreakdown,
  selectPublicationsByStatus,
  selectSuccessRate,
  type Dashboard,
} from "../../../src/entities/analytics"

const dashboard: Dashboard = {
  workspaceId: "ws-1",
  degraded: false,
  metrics: [
    {
      slug: METRIC_SLUGS.publicationsByStatus,
      title: "Publications by status over time",
      resultShape: "timeseries",
      degraded: false,
      rows: [
        { day: "2026-05-09", status: "published", total: 12 },
        { day: "2026-05-10", status: "failed", total: 2 },
      ],
    },
    {
      slug: METRIC_SLUGS.successRate,
      title: "Publish success rate",
      resultShape: "scalar",
      degraded: false,
      rows: [{ published: 241, failed: 15, total: 256, success_rate: 0.94 }],
    },
    {
      slug: METRIC_SLUGS.platformBreakdown,
      title: "Platform / channel breakdown",
      resultShape: "breakdown",
      degraded: false,
      rows: [
        { platform: "instagram", channel_id: "ch-a", total: 41 },
        { platform: "linkedin", channel_id: "ch-b", total: 86 },
      ],
    },
    {
      slug: METRIC_SLUGS.kpiCards,
      title: "KPI cards",
      resultShape: "kpi",
      degraded: false,
      rows: [
        { total_posts: 128, active_channels: 5, upcoming_publications: 14 },
      ],
    },
  ],
}

describe("analytics selectors", () => {
  it("selects publications-by-status rows by slug, not position", () => {
    const rows = selectPublicationsByStatus(dashboard)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toEqual({ day: "2026-05-09", status: "published", total: 12 })
  })

  it("maps success_rate snake_case → camelCase, single row", () => {
    expect(selectSuccessRate(dashboard)).toEqual({
      published: 241,
      failed: 15,
      total: 256,
      successRate: 0.94,
    })
  })

  it("sorts breakdown by total desc and maps channel_id → channelId", () => {
    const rows = selectPlatformBreakdown(dashboard)
    expect(rows[0]).toEqual({ platform: "linkedin", channelId: "ch-b", total: 86 })
    expect(rows[1].total).toBe(41)
  })

  it("maps kpi snake_case fields", () => {
    expect(selectKpi(dashboard)).toEqual({
      totalPosts: 128,
      activeChannels: 5,
      upcomingPublications: 14,
    })
  })

  it("returns null/empty for a missing metric", () => {
    const empty: Dashboard = { workspaceId: "ws", degraded: false, metrics: [] }
    expect(selectSuccessRate(empty)).toBeNull()
    expect(selectKpi(empty)).toBeNull()
    expect(selectPublicationsByStatus(empty)).toEqual([])
  })

  it("coerces unknown columns defensively (no throw on rename)", () => {
    const renamed: Dashboard = {
      workspaceId: "ws",
      degraded: false,
      metrics: [
        {
          slug: METRIC_SLUGS.kpiCards,
          title: "KPI",
          resultShape: "kpi",
          degraded: false,
          rows: [{ totalPosts: 9 }],
        },
      ],
    }
    expect(selectKpi(renamed)).toEqual({
      totalPosts: 0,
      activeChannels: 0,
      upcomingPublications: 0,
    })
  })

  it("detects per-metric degraded flag", () => {
    const degraded: Dashboard = {
      workspaceId: "ws",
      degraded: true,
      metrics: [
        {
          slug: METRIC_SLUGS.kpiCards,
          title: "KPI",
          resultShape: "kpi",
          degraded: true,
          rows: [],
        },
      ],
    }
    expect(isMetricDegraded(degraded, METRIC_SLUGS.kpiCards)).toBe(true)
    expect(isMetricDegraded(dashboard, METRIC_SLUGS.kpiCards)).toBe(false)
  })

  it("treats populated dashboard as non-empty", () => {
    expect(isDashboardEmpty(dashboard)).toBe(false)
  })

  it("treats undefined / no-metrics dashboard as empty", () => {
    expect(isDashboardEmpty(undefined)).toBe(true)
    const noMetrics: Dashboard = { workspaceId: "ws", degraded: false, metrics: [] }
    expect(isDashboardEmpty(noMetrics)).toBe(true)
  })

  it("treats all-metrics-empty (no rows, none degraded) as empty", () => {
    const allEmpty: Dashboard = {
      workspaceId: "ws",
      degraded: false,
      metrics: dashboard.metrics.map((m) => ({ ...m, degraded: false, rows: [] })),
    }
    expect(isDashboardEmpty(allEmpty)).toBe(true)
  })

  it("all metrics degraded → NOT empty (renders degraded tiles, not onboarding)", () => {
    // Full ClickHouse outage: every metric is degraded with empty rows.
    // isDashboardEmpty must return false so the page renders degraded tiles.
    const allDegraded: Dashboard = {
      workspaceId: "ws",
      degraded: true,
      metrics: dashboard.metrics.map((m) => ({ ...m, degraded: true, rows: [] })),
    }
    expect(isDashboardEmpty(allDegraded)).toBe(false)
  })

  it("partial degradation (some degraded, some with rows) → NOT empty", () => {
    const partial: Dashboard = {
      workspaceId: "ws",
      degraded: true,
      metrics: dashboard.metrics.map((m, i) =>
        i === 0 ? { ...m, degraded: true, rows: [] } : m,
      ),
    }
    expect(isDashboardEmpty(partial)).toBe(false)
  })
})
