import { describe, expect, it } from "vitest"
import { AxiosError } from "axios"

import { isModerationConflict } from "@/features/moderation/shared/conflict"

const axiosErrorWithStatus = (status: number): AxiosError => {
  const error = new AxiosError("boom")
  error.response = {
    status,
    statusText: "",
    data: {},
    headers: {},
    config: { headers: {} as never },
  }
  return error
}

describe("isModerationConflict", () => {
  it("treats 409 (already resolved) as a conflict", () => {
    expect(isModerationConflict(axiosErrorWithStatus(409))).toBe(true)
  })

  it("treats 404 (left the pending queue) as a conflict", () => {
    expect(isModerationConflict(axiosErrorWithStatus(404))).toBe(true)
  })

  it("does NOT treat 403 / 500 / network as a conflict", () => {
    expect(isModerationConflict(axiosErrorWithStatus(403))).toBe(false)
    expect(isModerationConflict(axiosErrorWithStatus(500))).toBe(false)
    expect(isModerationConflict(new Error("network"))).toBe(false)
    expect(isModerationConflict(null)).toBe(false)
  })
})
