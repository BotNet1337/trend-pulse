import { describe, expect, it } from "vitest"

import {
  formatCompact,
  formatPercent,
  resolveChannelLabel,
} from "../../../src/entities/analytics"
import type { Channel } from "../../../src/entities/channel"

const channel = (overrides: Partial<Channel>): Channel => ({
  id: "ch-1",
  workspaceId: "ws-1",
  userId: "u-1",
  platform: "instagram",
  name: "@acme",
  subject: "ig:1",
  status: "active",
  state: "active",
  meta: {},
  connectedAt: "2026-01-01T00:00:00Z",
  expiresAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  ...overrides,
})

describe("formatCompact", () => {
  it("renders small numbers in full", () => {
    expect(formatCompact(128)).toBe("128")
  })
  it("compacts large numbers", () => {
    expect(formatCompact(12400)).toMatch(/12/)
    expect(formatCompact(1_200_000)).toMatch(/1/)
  })
  it("guards against non-finite", () => {
    expect(formatCompact(Number.NaN)).toBe("0")
  })
})

describe("formatPercent", () => {
  it("rounds a 0..1 rate to whole percent", () => {
    expect(formatPercent(0.94)).toBe("94%")
    expect(formatPercent(0.005)).toBe("1%")
  })
  it("clamps out-of-range and guards NaN", () => {
    expect(formatPercent(1.5)).toBe("100%")
    expect(formatPercent(-1)).toBe("0%")
    expect(formatPercent(Number.NaN)).toBe("0%")
  })
})

describe("resolveChannelLabel", () => {
  it("prefers displayName, then name, then subject", () => {
    expect(
      resolveChannelLabel("ch-1", [channel({ meta: { displayName: "Acme IG" } })]),
    ).toBe("Acme IG")
    expect(resolveChannelLabel("ch-1", [channel({ name: "@acme" })])).toBe("@acme")
  })
  it("falls back to short id when channel is not in the list", () => {
    expect(resolveChannelLabel("abcdef12-3456", [])).toBe("#abcdef12")
  })
  it("returns an em-dash for empty id", () => {
    expect(resolveChannelLabel("", [])).toBe("—")
  })
})
