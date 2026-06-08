import type { Page } from "@playwright/test"

import type { MockChannel } from "./channels"

export type MockPostStatus =
  | "draft"
  | "publishing"
  | "published"
  | "failed"

export type MockPublicationStatus =
  | "pending"
  | "publishing"
  | "published"
  | "failed"

export interface MockPostMediaItem {
  id: string
  storageObjectId: string
  position: number
  state: "active" | "deleted"
  url?: string
  mimeType?: string
  createdAt: string
  updatedAt: string
}

export interface MockPublicationChannelRef {
  id: string
  name: string
  subject: string
  platform: MockChannel["platform"]
}

export interface MockPublication {
  id: string
  workspaceId: string
  postId: string
  channelId: string
  postType:
    | "instagram_feed"
    | "instagram_reels"
    | "instagram_stories"
    | "linkedin_personal"
    | "linkedin_organization"
    | "facebook_page_feed"
    | "facebook_page_reels"
    | "facebook_page_stories"
    | "youtube_video"
    | "youtube_shorts"
  status: MockPublicationStatus
  meta: Record<string, unknown>
  issue: { code: string; message: string } | null
  publishAt: string | null
  publishedAt: string | null
  attemptCount: number
  nextRetryAt: string | null
  lastAttemptAt: string | null
  state: "active" | "deleted"
  media: MockPostMediaItem[]
  channel: MockPublicationChannelRef
  createdAt: string
  updatedAt: string
}

export interface MockPostAggregate {
  id: string
  workspaceId: string
  authorId: string
  name: string
  description: string | null
  tags: string[]
  status: MockPostStatus
  state: "active" | "deleted"
  media: MockPostMediaItem[]
  publications: MockPublication[]
  author: { id: string; name: string | null; avatar: string | null }
  scheduledAt: string | null
  publishedAt: string | null
  counts: {
    total: number
    pending: number
    publishing: number
    published: number
    failed: number
  }
  createdAt: string
  updatedAt: string
}

const now = () => new Date().toISOString()

export const postFactory = (
  overrides: Partial<MockPostAggregate> & Pick<MockPostAggregate, "workspaceId">,
): MockPostAggregate => ({
  id: "55555555-5555-4555-8555-555555555555",
  authorId: "33333333-3333-4333-8333-333333333333",
  name: "First post",
  description: "Caption goes here.",
  tags: [],
  status: "draft",
  state: "active",
  media: [],
  publications: [],
  author: {
    id: "33333333-3333-4333-8333-333333333333",
    name: "Yarik",
    avatar: null,
  },
  scheduledAt: null,
  publishedAt: null,
  counts: {
    total: 0,
    pending: 0,
    publishing: 0,
    published: 0,
    failed: 0,
  },
  createdAt: now(),
  updatedAt: now(),
  ...overrides,
})

export const publicationFactory = (
  overrides: Partial<MockPublication> &
    Pick<MockPublication, "workspaceId" | "postId">,
): MockPublication => ({
  id: "66666666-6666-4666-8666-666666666666",
  channelId: "11111111-1111-4111-8111-111111111111",
  postType: "instagram_feed",
  status: "pending",
  meta: {},
  issue: null,
  publishAt: null,
  publishedAt: null,
  attemptCount: 0,
  nextRetryAt: null,
  lastAttemptAt: null,
  state: "active",
  media: [],
  channel: {
    id: "11111111-1111-4111-8111-111111111111",
    name: "@example",
    subject: "ig:1",
    platform: "instagram",
  },
  createdAt: now(),
  updatedAt: now(),
  ...overrides,
})

export interface PostsListMockHandle {
  setPosts: (next: MockPostAggregate[]) => void
}

export const mockPostsList = async (
  page: Page,
  workspaceId: string,
  initial: MockPostAggregate[],
): Promise<PostsListMockHandle> => {
  let current = initial
  await page.route(
    `**/api/workspaces/${workspaceId}/posts?**`,
    async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: current,
          meta: { total: current.length, offset: 0, limit: 60 },
        }),
      })
    },
  )
  return {
    setPosts: (next) => {
      current = next
    },
  }
}

export interface PostsCreateMockHandle {
  lastPayload: () => unknown
  setNextPost: (next: MockPostAggregate) => void
}

export const mockPostsCreate = async (
  page: Page,
  workspaceId: string,
  initial: MockPostAggregate,
): Promise<PostsCreateMockHandle> => {
  let nextPost = initial
  let lastPayload: unknown = null

  await page.route(
    `**/api/workspaces/${workspaceId}/posts`,
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback()
        return
      }
      lastPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(nextPost),
      })
    },
  )

  return {
    lastPayload: () => lastPayload,
    setNextPost: (post) => {
      nextPost = post
    },
  }
}

export const mockPostFindById = async (
  page: Page,
  workspaceId: string,
  postId: string,
  current: () => MockPostAggregate,
): Promise<void> => {
  await page.route(
    `**/api/workspaces/${workspaceId}/posts/${postId}`,
    async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current()),
      })
    },
  )
}

export const mockPostDelete = async (
  page: Page,
  workspaceId: string,
  postId: string,
): Promise<{ called: () => boolean }> => {
  let called = false
  await page.route(
    `**/api/workspaces/${workspaceId}/posts/${postId}`,
    async (route) => {
      if (route.request().method() === "DELETE") {
        called = true
        await route.fulfill({ status: 204, body: "" })
      } else {
        await route.fallback()
      }
    },
  )
  return { called: () => called }
}

export interface PostUpdateMockHandle {
  lastPayload: () => unknown
  setNextResponse: (post: MockPostAggregate) => void
}

export const mockPostUpdate = async (
  page: Page,
  workspaceId: string,
  postId: string,
  initialResponse: MockPostAggregate,
): Promise<PostUpdateMockHandle> => {
  let next = initialResponse
  let lastPayload: unknown = null
  await page.route(
    `**/api/workspaces/${workspaceId}/posts/${postId}`,
    async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback()
        return
      }
      lastPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(next),
      })
    },
  )
  return {
    lastPayload: () => lastPayload,
    setNextResponse: (post) => {
      next = post
    },
  }
}

export interface PublicationsCreateHandle {
  lastPayload: () => unknown
}

export const mockPublicationsCreate = async (
  page: Page,
  workspaceId: string,
  postId: string,
  buildResponse: (payload: unknown) => MockPublication[],
): Promise<PublicationsCreateHandle> => {
  let lastPayload: unknown = null
  await page.route(
    `**/api/workspaces/${workspaceId}/posts/${postId}/publications`,
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.fallback()
        return
      }
      lastPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(buildResponse(lastPayload)),
      })
    },
  )
  return { lastPayload: () => lastPayload }
}
