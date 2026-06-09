import { describe, expect, it } from "vitest"
import { QueryClient } from "@tanstack/react-query"

import { moderationQueueQueryKey } from "@/features/moderation/queue/model"
import {
  removeFromQueueOptimistically,
  restoreQueueSnapshot,
} from "@/features/moderation/shared/optimistic"
import type { ModerationQueueResponse } from "@/entities/moderation"

const item = (id: string) => ({
  id,
  postId: `post-${id}`,
  status: "pending" as const,
  workspace: { id: "ws", name: "WS" },
  author: { id: "a", name: "A" },
  post: {
    name: id,
    text: null,
    tags: [],
    mediaKind: "text" as const,
    mediaCount: 0,
    media: [],
  },
  channels: [],
  createdAt: "2026-06-07T10:00:00Z",
})

const seedQueue = (client: QueryClient, ids: string[]) => {
  const data: ModerationQueueResponse = {
    data: ids.map(item),
    total: ids.length,
  }
  client.setQueryData(moderationQueueQueryKey(), data)
}

describe("removeFromQueueOptimistically", () => {
  it("drops the target row and decrements total across cached pages", async () => {
    const client = new QueryClient()
    seedQueue(client, ["a", "b", "c"])

    await removeFromQueueOptimistically(client, "b")

    const after = client.getQueryData<ModerationQueueResponse>(
      moderationQueueQueryKey(),
    )
    expect(after?.data.map((i) => i.id)).toEqual(["a", "c"])
    expect(after?.total).toBe(2)
  })

  it("returns a snapshot that restores the original queue", async () => {
    const client = new QueryClient()
    seedQueue(client, ["a", "b"])

    const snapshot = await removeFromQueueOptimistically(client, "a")
    restoreQueueSnapshot(client, snapshot)

    const restored = client.getQueryData<ModerationQueueResponse>(
      moderationQueueQueryKey(),
    )
    expect(restored?.data.map((i) => i.id)).toEqual(["a", "b"])
    expect(restored?.total).toBe(2)
  })

  it("never lets total go negative", async () => {
    const client = new QueryClient()
    client.setQueryData(moderationQueueQueryKey(), { data: [], total: 0 })

    await removeFromQueueOptimistically(client, "missing")

    const after = client.getQueryData<ModerationQueueResponse>(
      moderationQueueQueryKey(),
    )
    // No matching schema-valid cache row to mutate → unchanged.
    expect(after?.total).toBe(0)
  })
})
