import { describe, expect, it } from "vitest"

import {
  customRange,
  defaultDateRange,
  presetRange,
  rangeBucket,
} from "../../../src/entities/analytics"

describe("presetRange", () => {
  const now = new Date("2026-06-07T15:30:00Z")

  it("spans N calendar days inclusive of today, full ISO datetime bounds", () => {
    const range = presetRange("7d", now)
    expect(range.preset).toBe("7d")
    // Both bounds are full ISO-8601 datetimes.
    expect(range.from).toMatch(/^\d{4}-\d{2}-\d{2}T/)
    expect(range.to).toMatch(/^\d{4}-\d{2}-\d{2}T/)
    expect(new Date(range.from).getTime()).toBeLessThan(
      new Date(range.to).getTime(),
    )
  })

  it("90d preset is wider than 7d", () => {
    const wide = presetRange("90d", now)
    const narrow = presetRange("7d", now)
    expect(new Date(wide.from).getTime()).toBeLessThan(
      new Date(narrow.from).getTime(),
    )
  })

  it("default range is the 30-day preset", () => {
    expect(defaultDateRange(now).preset).toBe("30d")
  })
})

describe("customRange", () => {
  it("normalises swapped bounds and tags preset 'custom'", () => {
    const range = customRange(
      new Date("2026-06-07"),
      new Date("2026-05-01"),
    )
    expect(range.preset).toBe("custom")
    expect(new Date(range.from).getTime()).toBeLessThan(
      new Date(range.to).getTime(),
    )
  })
})

describe("rangeBucket", () => {
  it("is day-granular and stable across sub-second skew", () => {
    const a = { preset: "30d" as const, from: "2026-05-09T00:00:00.001Z", to: "2026-06-07T23:59:59.500Z" }
    const b = { preset: "30d" as const, from: "2026-05-09T00:00:00.999Z", to: "2026-06-07T23:59:59.999Z" }
    expect(rangeBucket(a)).toBe(rangeBucket(b))
    expect(rangeBucket(a)).toBe("2026-05-09/2026-06-07")
  })
})
