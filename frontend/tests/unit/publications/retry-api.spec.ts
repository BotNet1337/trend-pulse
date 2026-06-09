import { describe, expect, it, vi } from "vitest"
import type { AxiosInstance } from "axios"

import { retryPublication, retryPublicationPath } from "@/features/publications"

const WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
const POST_ID = "22222222-2222-2222-2222-222222222222"
const PUBLICATION_ID = "33333333-3333-3333-3333-333333333333"

describe("retryPublication api", () => {
  it("builds the JWT retry path with all three ids", async () => {
    const client = { post: vi.fn().mockResolvedValue({ data: undefined }) }

    await retryPublication(
      {
        workspaceId: WORKSPACE_ID,
        postId: POST_ID,
        publicationId: PUBLICATION_ID,
      },
      client as unknown as AxiosInstance,
    )

    expect(client.post).toHaveBeenCalledWith(
      `/workspaces/${WORKSPACE_ID}/posts/${POST_ID}/publications/${PUBLICATION_ID}/retry`,
    )
  })

  it("uses the retry route under the workspace/post/publication path", () => {
    expect(retryPublicationPath).toBe(
      "/workspaces/{workspaceId}/posts/{postId}/publications/{publicationId}/retry",
    )
  })
})
