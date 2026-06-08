import { describe, expect, it, vi } from "vitest"
import type { AxiosInstance } from "axios"

import { fetchDashboard } from "../../../../../server/ssr/prefetch/fetchers"
import type { FetcherCtx } from "../../../../../server/ssr/prefetch/types"

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

const buildCtx = (overrides: Partial<FetcherCtx> = {}): FetcherCtx => ({
  api: { get: vi.fn(async () => ({ data: okEnvelope })) } as unknown as AxiosInstance,
  signal: new AbortController().signal,
  params: {},
  search: new URLSearchParams(),
  ...overrides,
})

describe("fetchDashboard", () => {
  it("returns null without a workspaceId param", async () => {
    const ctx = buildCtx()
    expect(await fetchDashboard(ctx)).toBeNull()
  })

  it("fetches the dashboard and keys it for hydration", async () => {
    const ctx = buildCtx({ params: { workspaceId: "ws-1" } })
    const result = await fetchDashboard(ctx)
    expect(result).not.toBeNull()
    expect(result?.key).toBeInstanceOf(Array)
    expect(result?.key).toContain("ws-1")
    // Key ends with the day-bucket segment used by the runtime hook.
    expect(String(result?.key.at(-1))).toMatch(/^\d{4}-\d{2}-\d{2}\/\d{4}-\d{2}-\d{2}$/)
  })
})
