import { describe, expect, it } from "vitest"

import {
  POST_PREVIEW_UNAVAILABLE,
  isRejectReasonValid,
  moderationRawQueueResponseSchema,
  moderationRawRequestSchema,
  parseModerationQueueResponse,
  parseModerationRequestDetail,
  rejectReasonSchema,
} from "@/entities/moderation"

/**
 * The REAL TASK-071 (`feat/task-071c-moderation-reorder`) read-model is FLAT:
 * `{ id, postId, workspaceId, authorId, status, intent:{channels[]}, reviews[],
 * createdAt, updatedAt }` — no embedded post preview, no resolved
 * workspace/author names, no channel platform/name. These fixtures mirror that
 * actual wire shape (the regression lock the review asked for).
 */
const flatQueueItem = {
  id: "req-1",
  postId: "post-1",
  workspaceId: "ws-1",
  authorId: "u-1",
  status: "pending" as const,
  intent: {
    channels: [
      { channelId: "c-1", postType: "linkedin_personal", meta: {} },
      { channelId: "c-2", postType: "facebook_page_feed", meta: {} },
    ],
  },
  createdAt: "2026-06-07T10:00:00Z",
  updatedAt: "2026-06-07T10:00:00Z",
}

const flatDetail = {
  ...flatQueueItem,
  reviews: [
    {
      id: "rev-1",
      requestId: "req-1",
      reviewerId: "admin-1",
      decision: "reject" as const,
      reason: "off-brand",
      createdAt: "2026-06-07T11:00:00Z",
    },
  ],
}

describe("rejectReasonSchema", () => {
  it("rejects empty / whitespace-only reasons", () => {
    expect(isRejectReasonValid("")).toBe(false)
    expect(isRejectReasonValid("   ")).toBe(false)
  })

  it("accepts a non-empty reason and trims it", () => {
    expect(isRejectReasonValid("spam")).toBe(true)
    expect(rejectReasonSchema.parse("  spam  ")).toBe("spam")
  })

  it("rejects reasons over 2000 chars", () => {
    expect(isRejectReasonValid("a".repeat(2001))).toBe(false)
  })
})

describe("flat 071 queue boundary + adapter", () => {
  it("parses the REAL flat 071 queue payload (no throw)", () => {
    expect(() =>
      moderationRawQueueResponseSchema.parse({
        data: [flatQueueItem],
        total: 1,
      }),
    ).not.toThrow()
  })

  it("adapts a flat queue item to a view-model with safe placeholders", () => {
    const { data, total } = parseModerationQueueResponse({
      data: [flatQueueItem],
      total: 1,
    })
    expect(total).toBe(1)
    const item = data[0]

    // post preview synthesised from postId — never throws on the flat shape
    expect(item.post.name).toContain("post-1")
    expect(item.post.text).toBe(POST_PREVIEW_UNAVAILABLE)
    expect(item.post.tags).toEqual([])
    expect(item.post.mediaKind).toBe("text")
    expect(item.post.media).toEqual([])

    // workspace/author fall back to ids with null names (id-based UI fallback)
    expect(item.workspace).toEqual({ id: "ws-1", name: null })
    expect(item.author).toEqual({ id: "u-1", name: null })

    // channels come from intent.channels[]; platform unknown → null (neutral chip)
    expect(item.channels).toEqual([
      { channelId: "c-1", postType: "linkedin_personal", platform: null, name: null },
      { channelId: "c-2", postType: "facebook_page_feed", platform: null, name: null },
    ])
  })

  it("tolerates extra meta on intent channels (ignores unknown keys)", () => {
    expect(() =>
      moderationRawQueueResponseSchema.parse({
        data: [
          {
            ...flatQueueItem,
            intent: {
              channels: [
                {
                  channelId: "c-9",
                  postType: "x",
                  meta: { organizationUrn: "urn:li:org:1" },
                },
              ],
            },
          },
        ],
        total: 1,
      }),
    ).not.toThrow()
  })

  it("throws only on a genuinely malformed payload (missing required id)", () => {
    expect(() =>
      moderationRawQueueResponseSchema.parse({
        data: [{ ...flatQueueItem, id: "" }],
        total: 1,
      }),
    ).toThrow()
  })
})

describe("flat 071 detail boundary + adapter", () => {
  it("parses the REAL flat 071 detail payload and renders reviews[]", () => {
    const detail = parseModerationRequestDetail(flatDetail)
    expect(detail.reviews).toHaveLength(1)
    expect(detail.reviews[0].decision).toBe("reject")
    expect(detail.reviews[0].reason).toBe("off-brand")
    // reviewerName is enrichment-only — absent in flat 071 → null placeholder
    expect(detail.reviews[0].reviewerName).toBeNull()
    expect(detail.post.text).toBe(POST_PREVIEW_UNAVAILABLE)
  })

  it("defaults reviews[] to empty when omitted", () => {
    const parsed = moderationRawRequestSchema.parse(flatQueueItem)
    expect(parsed.reviews).toEqual([])
  })
})

describe("forward-compat: enriched 071 read-model", () => {
  it("prefers enriched fields when the backend later provides them", () => {
    const { data } = parseModerationQueueResponse({
      data: [
        {
          ...flatQueueItem,
          post: {
            name: "Week 22",
            text: "Дайджест",
            tags: ["release"],
            mediaKind: "image",
            mediaCount: 1,
            media: [{ id: "m-1", url: "https://x/y.png", mimeType: "image/png" }],
          },
          workspace: { id: "ws-1", name: "Acme" },
          author: { id: "u-1", name: "Иван" },
          intent: {
            channels: [
              {
                channelId: "c-1",
                postType: "linkedin_personal",
                meta: {},
                platform: "linkedin",
                name: "@acme",
              },
            ],
          },
        },
      ],
      total: 1,
    })
    const item = data[0]
    expect(item.post.name).toBe("Week 22")
    expect(item.post.text).toBe("Дайджест")
    expect(item.workspace.name).toBe("Acme")
    expect(item.author.name).toBe("Иван")
    expect(item.channels[0].platform).toBe("linkedin")
    expect(item.channels[0].name).toBe("@acme")
  })

  it("rejects an enriched channel with an unknown platform", () => {
    expect(() =>
      moderationRawQueueResponseSchema.parse({
        data: [
          {
            ...flatQueueItem,
            intent: {
              channels: [
                { channelId: "c", postType: "x", meta: {}, platform: "tiktok" },
              ],
            },
          },
        ],
        total: 1,
      }),
    ).toThrow()
  })
})
