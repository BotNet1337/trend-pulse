import { describe, expect, it } from "vitest"

import {
  PAT_SCOPE_PRESETS,
  canRegeneratePat,
  canRevokePat,
  formatExpiry,
  formatLastUsed,
  issuedPatSchema,
  matchScopePreset,
  publicPatListSchema,
  publicPatSchema,
} from "@/entities/pat"

describe("matchScopePreset", () => {
  it("matches the PUBLISHING preset regardless of order", () => {
    expect(
      matchScopePreset([
        "channels:read",
        "publications:write",
        "posts:write",
        "storage:write",
      ]),
    ).toBe("PUBLISHING")
  })

  it("matches the READ_ONLY preset", () => {
    expect(matchScopePreset([...PAT_SCOPE_PRESETS.READ_ONLY])).toBe("READ_ONLY")
  })

  it("returns null for a custom combination", () => {
    expect(matchScopePreset(["posts:write"])).toBeNull()
  })

  it("returns null when a preset is a strict subset (extra scope present)", () => {
    expect(
      matchScopePreset([...PAT_SCOPE_PRESETS.READ_ONLY, "storage:write"]),
    ).toBeNull()
  })
})

describe("status gates", () => {
  it("allows regenerate/revoke only for active tokens", () => {
    expect(canRegeneratePat("active")).toBe(true)
    expect(canRegeneratePat("expired")).toBe(false)
    expect(canRegeneratePat("revoked")).toBe(false)
    expect(canRevokePat("active")).toBe(true)
    expect(canRevokePat("expired")).toBe(false)
  })
})

describe("meta formatting", () => {
  it("formats expiry / no-expiry", () => {
    expect(formatExpiry(null)).toBe("No expiry")
    expect(formatExpiry("2027-01-01T00:00:00.000Z")).toMatch(/^Expires /)
  })

  it("formats last-used", () => {
    expect(formatLastUsed(null)).toBe("Never used")
    expect(formatLastUsed(new Date().toISOString())).toBe("Used today")
  })
})

describe("boundary schemas", () => {
  const publicPat = {
    id: "11111111-1111-1111-1111-111111111111",
    fingerprint: "pb_pat_a1b2c3d4",
    name: "CI",
    scopes: ["posts:write"],
    status: "active",
    expiresAt: null,
    lastUsedAt: null,
    revokedAt: null,
    createdAt: "2026-06-01T00:00:00.000Z",
    updatedAt: "2026-06-01T00:00:00.000Z",
  }

  it("parses a valid public PAT and a list", () => {
    expect(() => publicPatSchema.parse(publicPat)).not.toThrow()
    expect(() => publicPatListSchema.parse([publicPat])).not.toThrow()
  })

  it("rejects an unknown status", () => {
    expect(() =>
      publicPatSchema.parse({ ...publicPat, status: "frozen" }),
    ).toThrow()
  })

  it("parses the issued envelope including the one-time token", () => {
    const issued = issuedPatSchema.parse({
      id: "11111111-1111-1111-1111-111111111111",
      token: "pb_pat_a1b2c3d4xyz0123456789012345678901234567890",
      fingerprint: "pb_pat_a1b2c3d4",
      name: "CI",
      scopes: ["posts:write"],
      expiresAt: null,
      createdAt: "2026-06-01T00:00:00.000Z",
    })
    expect(issued.token).toContain("pb_pat_")
  })

  it("rejects an issued envelope missing the token", () => {
    expect(() =>
      issuedPatSchema.parse({
        id: "11111111-1111-1111-1111-111111111111",
        fingerprint: "pb_pat_a1b2c3d4",
        name: "CI",
        scopes: ["posts:write"],
        expiresAt: null,
        createdAt: "2026-06-01T00:00:00.000Z",
      }),
    ).toThrow()
  })
})
