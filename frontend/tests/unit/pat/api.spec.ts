import { describe, expect, it, vi } from "vitest"
import type { AxiosInstance } from "axios"

import {
  createPat,
  listPats,
  patsQueryKey,
  regeneratePat,
  revokePat,
} from "@/features/pat"

const WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
const PAT_ID = "22222222-2222-2222-2222-222222222222"

const publicPat = {
  id: PAT_ID,
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

const issued = {
  id: PAT_ID,
  token: "pb_pat_a1b2c3d4xyz0123456789012345678901234567890",
  fingerprint: "pb_pat_a1b2c3d4",
  name: "CI",
  scopes: ["posts:write"],
  expiresAt: null,
  createdAt: "2026-06-01T00:00:00.000Z",
}

const fakeClient = () =>
  ({
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  }) as unknown as AxiosInstance

describe("PAT api client", () => {
  it("listPats sends X-Workspace-Id header and validates the response", async () => {
    const client = fakeClient()
    vi.mocked(client.get).mockResolvedValue({ data: [publicPat] })

    const result = await listPats(WORKSPACE_ID, client)

    expect(client.get).toHaveBeenCalledWith("/me/pats", {
      headers: { "X-Workspace-Id": WORKSPACE_ID },
    })
    expect(result).toHaveLength(1)
    expect(result[0].fingerprint).toBe("pb_pat_a1b2c3d4")
  })

  it("createPat posts the body + header and returns the one-time token", async () => {
    const client = fakeClient()
    vi.mocked(client.post).mockResolvedValue({ data: issued })

    const result = await createPat(
      {
        workspaceId: WORKSPACE_ID,
        name: "CI",
        scopes: ["posts:write"],
        expiresAt: null,
      },
      client,
    )

    expect(client.post).toHaveBeenCalledWith(
      "/me/pats",
      { name: "CI", scopes: ["posts:write"], expiresAt: null },
      { headers: { "X-Workspace-Id": WORKSPACE_ID } },
    )
    expect(result.token).toContain("pb_pat_")
  })

  it("regeneratePat threads the immediate query flag", async () => {
    const client = fakeClient()
    vi.mocked(client.post).mockResolvedValue({ data: issued })

    await regeneratePat(
      { workspaceId: WORKSPACE_ID, patId: PAT_ID, immediate: true },
      client,
    )

    expect(client.post).toHaveBeenCalledWith(
      `/me/pats/${PAT_ID}/regenerate`,
      undefined,
      {
        params: { immediate: true },
        headers: { "X-Workspace-Id": WORKSPACE_ID },
      },
    )
  })

  it("revokePat deletes by id with the workspace header", async () => {
    const client = fakeClient()
    vi.mocked(client.delete).mockResolvedValue({ data: undefined })

    await revokePat({ workspaceId: WORKSPACE_ID, patId: PAT_ID }, client)

    expect(client.delete).toHaveBeenCalledWith(`/me/pats/${PAT_ID}`, {
      headers: { "X-Workspace-Id": WORKSPACE_ID },
    })
  })

  it("rejects a malformed list payload at the boundary", async () => {
    const client = fakeClient()
    vi.mocked(client.get).mockResolvedValue({ data: [{ id: "not-a-uuid" }] })

    await expect(listPats(WORKSPACE_ID, client)).rejects.toThrow()
  })

  it("query key is workspace-scoped", () => {
    expect(patsQueryKey(WORKSPACE_ID)).toEqual(["me", "pats", WORKSPACE_ID])
  })
})
