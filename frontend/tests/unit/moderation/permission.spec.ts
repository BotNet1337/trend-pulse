import { describe, expect, it } from "vitest"

import {
  canModerateContent,
  MODERATE_CONTENT_PERMISSION,
} from "@/entities/moderation"

describe("canModerateContent", () => {
  it("returns false for null / undefined (not resolved → hidden)", () => {
    expect(canModerateContent(null)).toBe(false)
    expect(canModerateContent(undefined)).toBe(false)
  })

  it("returns false for the current JwtUser shape (no permission claims yet)", () => {
    // Mirrors today's auth-store value (TASK-069/070 not merged).
    const jwtUser = {
      userId: "u1",
      accountId: "a1",
      email: "x@y.z",
      provider: "email",
    }
    expect(canModerateContent(jwtUser)).toBe(false)
  })

  it("returns true when the explicit ModerateContent permission is present", () => {
    expect(
      canModerateContent({ permissions: [MODERATE_CONTENT_PERMISSION] }),
    ).toBe(true)
  })

  it("returns true for an admin role (case-insensitive)", () => {
    expect(canModerateContent({ roles: ["Admin"] })).toBe(true)
    expect(canModerateContent({ roles: ["ADMIN"] })).toBe(true)
  })

  it("returns false for a non-admin role without the permission", () => {
    expect(canModerateContent({ roles: ["member"], permissions: [] })).toBe(
      false,
    )
  })

  it("tolerates malformed input without throwing", () => {
    expect(canModerateContent({ permissions: "nope" })).toBe(false)
    expect(canModerateContent(42)).toBe(false)
    expect(canModerateContent("string")).toBe(false)
  })
})
