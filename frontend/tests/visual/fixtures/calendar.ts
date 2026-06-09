import type { Locator, Page } from "@playwright/test"

import {
  postFactory,
  publicationFactory,
  type MockPostAggregate,
  type MockPublication,
  type MockPublicationChannelRef,
} from "./posts"

/**
 * Convenience builder for calendar fixtures: a post with N publications
 * scheduled across multiple days. Each entry in `slots` becomes one
 * publication on the post.
 */
export interface CalendarSlot {
  /** ISO 8601 string — when this publication is scheduled / published. */
  publishAt: string
  /** Override status; default `pending`. */
  status?: MockPublication["status"]
  /** When the post is `published`, set the realised time here. */
  publishedAt?: string | null
  channel?: Partial<MockPublicationChannelRef>
  postType?: MockPublication["postType"]
  publicationId?: string
}

export interface BuildCalendarPostOptions {
  workspaceId: string
  postId: string
  name: string
  status?: MockPostAggregate["status"]
  slots: CalendarSlot[]
}

export const buildCalendarPost = (
  options: BuildCalendarPostOptions,
): MockPostAggregate => {
  const publications = options.slots.map((slot, idx): MockPublication =>
    publicationFactory({
      workspaceId: options.workspaceId,
      postId: options.postId,
      id: slot.publicationId ?? `66666666-6666-4666-8666-66666666${String(idx).padStart(4, "0")}`,
      status: slot.status ?? "pending",
      publishAt: slot.publishAt,
      publishedAt: slot.publishedAt ?? null,
      postType: slot.postType ?? "instagram_feed",
      channel: {
        id: slot.channel?.id ?? "11111111-1111-4111-8111-111111111111",
        name: slot.channel?.name ?? "@example",
        subject: slot.channel?.subject ?? "ig:1",
        platform: slot.channel?.platform ?? "instagram",
      },
    }),
  )

  return postFactory({
    workspaceId: options.workspaceId,
    id: options.postId,
    name: options.name,
    status: options.status ?? "draft",
    publications,
    counts: {
      total: publications.length,
      pending: publications.filter((p) => p.status === "pending").length,
      publishing: publications.filter((p) => p.status === "publishing").length,
      published: publications.filter((p) => p.status === "published").length,
      failed: publications.filter((p) => p.status === "failed").length,
    },
  })
}

/**
 * Playwright's built-in `dragTo` simulates pointer events, which the browser
 * does NOT translate into HTML5 `dragstart`/`drop` events — so the calendar's
 * `dataTransfer.getData(...)` always sees an empty string and the drop
 * handler bails out. We dispatch the drag sequence directly via the browser
 * runtime so `dataTransfer` is preserved end-to-end.
 */
export const performHtml5Drag = async (
  page: Page,
  source: Locator,
  target: Locator,
): Promise<void> => {
  const sourceHandle = await source.elementHandle()
  const targetHandle = await target.elementHandle()
  if (!sourceHandle || !targetHandle) {
    throw new Error("performHtml5Drag: source/target locator did not resolve")
  }
  await page.evaluate(
    ({ src, dst }) => {
      const dt = new DataTransfer()
      const fire = (_el: Element, type: string, target: Element) => {
        const event = new DragEvent(type, {
          bubbles: true,
          cancelable: true,
          dataTransfer: dt,
        })
        // jsdom-style runtime sometimes seals dataTransfer; reassign through
        // defineProperty so the calendar's `event.dataTransfer.setData(...)`
        // call reaches the same instance the drop handler reads from.
        Object.defineProperty(event, "dataTransfer", { value: dt })
        target.dispatchEvent(event)
      }
      fire(src, "dragstart", src)
      fire(dst, "dragenter", dst)
      fire(dst, "dragover", dst)
      fire(dst, "drop", dst)
      fire(src, "dragend", src)
    },
    { src: sourceHandle, dst: targetHandle },
  )
}

export interface ReschedulePublicationCall {
  workspaceId: string
  postId: string
  publicationId: string
  body: { publishAt: string }
}

export interface ReschedulePublicationHandle {
  calls: () => ReschedulePublicationCall[]
}

/**
 * Routes PATCH `/workspaces/.../publications/:id` and records the body so
 * tests can assert on the rescheduled `publishAt`.
 */
export const mockReschedulePublication = async (
  page: Page,
  workspaceId: string,
): Promise<ReschedulePublicationHandle> => {
  const calls: ReschedulePublicationCall[] = []

  await page.route(
    `**/api/workspaces/${workspaceId}/posts/*/publications/*`,
    async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.fallback()
        return
      }
      const url = new URL(route.request().url())
      const segments = url.pathname.split("/")
      const postId = segments[segments.length - 3]
      const publicationId = segments[segments.length - 1]
      const body = (route.request().postDataJSON() ?? {}) as { publishAt?: string }
      calls.push({
        workspaceId,
        postId,
        publicationId,
        body: { publishAt: body.publishAt ?? "" },
      })
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: publicationId,
          postId,
          workspaceId,
          channelId: "11111111-1111-4111-8111-111111111111",
          postType: "instagram_feed",
          status: "pending",
          meta: {},
          issue: null,
          publishAt: body.publishAt ?? null,
          publishedAt: null,
          attemptCount: 0,
          nextRetryAt: null,
          lastAttemptAt: null,
          state: "active",
          media: [],
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        }),
      })
    },
  )

  return {
    calls: () => calls,
  }
}
