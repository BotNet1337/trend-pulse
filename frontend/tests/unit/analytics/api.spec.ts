import { describe, expect, it, vi } from "vitest"
import type { AxiosInstance } from "axios"

import {
  dashboardQueryFromRange,
  getDashboard,
} from "../../../src/features/analytics/dashboard/api"
import { dashboardQueryKey } from "../../../src/features/analytics/dashboard/model"
import { defaultDateRange, presetRange } from "../../../src/entities/analytics"

const okEnvelope = {
  workspaceId: "ws-1",
  degraded: false,
  metrics: [
    {
      slug: "kpi-cards",
      title: "KPI cards",
      resultShape: "kpi",
      degraded: false,
      rows: [{ total_posts: 1, active_channels: 2, upcoming_publications: 3 }],
    },
  ],
}

const mockClient = (data: unknown): AxiosInstance => {
  const get = vi.fn(async () => ({ data }))
  return { get } as unknown as AxiosInstance
}

describe("getDashboard", () => {
  it("hits the workspace-scoped dashboard path with from/to query", async () => {
    const client = mockClient(okEnvelope)
    const range = defaultDateRange()
    await getDashboard(
      { workspaceId: "ws-1" },
      dashboardQueryFromRange(range),
      client,
    )
    const getMock = client.get as unknown as ReturnType<typeof vi.fn>
    const [url, config] = getMock.mock.calls[0]
    expect(url).toBe("/workspaces/ws-1/analytics/dashboard")
    expect(config.params.from).toBe(range.from)
    expect(config.params.to).toBe(range.to)
  })

  it("parses the envelope through the Zod guard", async () => {
    const result = await getDashboard(
      { workspaceId: "ws-1" },
      { from: "a", to: "b" },
      mockClient(okEnvelope),
    )
    expect(result.metrics[0].slug).toBe("kpi-cards")
  })

  it("throws on a malformed payload (boundary validation)", async () => {
    await expect(
      getDashboard(
        { workspaceId: "ws-1" },
        { from: "a", to: "b" },
        mockClient({ workspaceId: "ws-1" }),
      ),
    ).rejects.toThrow()
  })
})

describe("dashboardQueryKey", () => {
  it("changes when the workspace changes", () => {
    const range = defaultDateRange()
    expect(dashboardQueryKey("ws-1", range)).not.toEqual(
      dashboardQueryKey("ws-2", range),
    )
  })

  it("changes when the range changes", () => {
    const now = new Date("2026-06-07T00:00:00Z")
    expect(dashboardQueryKey("ws-1", presetRange("7d", now))).not.toEqual(
      dashboardQueryKey("ws-1", presetRange("90d", now)),
    )
  })
})
