import { describe, expect, it } from "vitest"

import { buildSeries } from "../../../src/features/analytics/lib/build-series"

describe("buildSeries", () => {
  it("returns no days for empty input", () => {
    const result = buildSeries([])
    expect(result.days).toEqual([])
    expect(result.max).toBe(1)
  })

  it("pivots rows into one polyline per status over sorted unique days", () => {
    const result = buildSeries([
      { day: "2026-05-10", status: "published", total: 5 },
      { day: "2026-05-09", status: "published", total: 12 },
      { day: "2026-05-09", status: "failed", total: 2 },
    ])
    expect(result.days).toEqual(["2026-05-09", "2026-05-10"])
    expect(result.max).toBe(12)
    // Three configured series (published / failed / scheduled).
    expect(result.series).toHaveLength(3)
    const published = result.series.find((s) => s.status === "published")
    expect(published?.points.split(" ")).toHaveLength(2)
  })

  it("scales the highest value toward the top of the viewbox", () => {
    const result = buildSeries([
      { day: "d1", status: "published", total: 10 },
      { day: "d2", status: "published", total: 10 },
    ])
    const published = result.series.find((s) => s.status === "published")
    // y for the max value should be small (near top); 200 is the bottom.
    const firstY = Number(published?.points.split(" ")[0]?.split(",")[1])
    expect(firstY).toBeLessThan(200)
  })
})
