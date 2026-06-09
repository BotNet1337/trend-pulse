import type { Page } from "@playwright/test"

/**
 * E2E fixtures mirror the REAL TASK-071 (`feat/task-071c-moderation-reorder`)
 * FLAT read-model wire shape: `{ id, postId, workspaceId, authorId, status,
 * intent:{channels[]}, reviews[], createdAt, updatedAt }` — no embedded post
 * preview, no resolved workspace/author names, no channel platform/name. The
 * frontend's boundary adapter fills enrichment placeholders, so the queue/detail
 * render cleanly off this flat payload.
 */
export interface MockModerationIntentChannel {
  channelId: string
  postType: string
  meta: Record<string, unknown>
}

export interface MockModerationItem {
  id: string
  postId: string
  workspaceId: string
  authorId: string
  status: "pending" | "approved" | "rejected"
  intent: { channels: MockModerationIntentChannel[] }
  createdAt: string
  updatedAt: string
}

export const moderationItemFactory = (
  overrides: Partial<MockModerationItem> & Pick<MockModerationItem, "id">,
): MockModerationItem => ({
  postId: `post-${overrides.id}`,
  workspaceId: "ws-1",
  authorId: "author-1",
  status: "pending",
  intent: {
    channels: [
      { channelId: "c-1", postType: "linkedin_personal", meta: {} },
      { channelId: "c-2", postType: "facebook_page_feed", meta: {} },
    ],
  },
  createdAt: new Date(Date.now() - 5 * 60_000).toISOString(),
  updatedAt: new Date(Date.now() - 5 * 60_000).toISOString(),
  ...overrides,
})

/**
 * Grants the in-browser session the `ModerateContent` permission by augmenting
 * the SSR-injected `__INITIAL_STATE__.user` before the app hydrates. The
 * permission concept ships with TASK-069/070 (not merged); this stands in for
 * that future `roles`/`permissions` claim so the e2e can exercise the
 * admin-gated nav + page. Real protection remains the API 403.
 */
export const grantModeratePermission = async (page: Page): Promise<void> => {
  await page.addInitScript(() => {
    const w = window as unknown as {
      __INITIAL_STATE__?: { user?: Record<string, unknown> | null }
    }
    const state = w.__INITIAL_STATE__ ?? {}
    const user = state.user ?? {
      userId: "admin-1",
      accountId: "acc-1",
      provider: "email",
    }
    w.__INITIAL_STATE__ = { ...state, user: { ...user, roles: ["admin"] } }
  })
}

/**
 * Mocks the moderation API surface (TASK-071, not merged) with the REAL flat
 * read-model shape. Returns helpers to read which approve/reject calls landed
 * and to swap the queue payload.
 */
export const mockModerationApi = async (
  page: Page,
  initial: MockModerationItem[],
): Promise<{
  setQueue: (next: MockModerationItem[]) => void
  approvedIds: string[]
  rejected: Array<{ id: string; reason: string }>
}> => {
  let queue = initial
  const approvedIds: string[] = []
  const rejected: Array<{ id: string; reason: string }> = []

  await page.route("**/api/moderation/queue?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: queue, total: queue.length }),
    })
  })

  await page.route("**/api/moderation/*/approve", async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split("/").at(-2) ?? ""
    approvedIds.push(id)
    queue = queue.filter((item) => item.id !== id)
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ request: { id, status: "approved" }, publications: [] }),
    })
  })

  await page.route("**/api/moderation/*/reject", async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split("/").at(-2) ?? ""
    const bodyRaw = route.request().postData() ?? "{}"
    const body = JSON.parse(bodyRaw) as { reason?: string }
    rejected.push({ id, reason: body.reason ?? "" })
    queue = queue.filter((item) => item.id !== id)
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ request: { id, status: "rejected" } }),
    })
  })

  // Detail endpoint — matches /api/moderation/:id but not the action subpaths.
  await page.route("**/api/moderation/*", async (route) => {
    const url = new URL(route.request().url())
    const tail = url.pathname.split("/").at(-1) ?? ""
    if (tail === "queue" || tail === "approve" || tail === "reject") {
      await route.fallback()
      return
    }
    const id = tail
    const item = queue.find((q) => q.id === id) ?? moderationItemFactory({ id })
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...item, reviews: [] }),
    })
  })

  return {
    setQueue: (next) => {
      queue = next
    },
    get approvedIds() {
      return approvedIds
    },
    get rejected() {
      return rejected
    },
  }
}
