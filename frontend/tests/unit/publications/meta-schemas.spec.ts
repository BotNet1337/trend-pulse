import { describe, expect, it } from "vitest"

import { cleanPostTypeMeta } from "@/features/publications/post-types"

describe("cleanPostTypeMeta — existing fields", () => {
  it("strips empty optionals to nothing", () => {
    expect(cleanPostTypeMeta("instagram_feed", {})).toEqual({})
  })

  it("accepts a valid linkedin organization urn", () => {
    expect(
      cleanPostTypeMeta("linkedin_organization", {
        organizationUrn: "urn:li:organization:1234567",
      }),
    ).toEqual({ organizationUrn: "urn:li:organization:1234567" })
  })

  it("rejects a malformed organization urn", () => {
    expect(() =>
      cleanPostTypeMeta("linkedin_organization", { organizationUrn: "nope" }),
    ).toThrow()
  })
})

describe("cleanPostTypeMeta — new TASK-048 fields", () => {
  it("strips empty new instagram feed optionals", () => {
    expect(
      cleanPostTypeMeta("instagram_feed", {
        userTags: [],
        productTags: "",
        locationId: "  ",
      }),
    ).toEqual({})
  })

  it("parses instagram feed user tags, product tags and location", () => {
    expect(
      cleanPostTypeMeta("instagram_feed", {
        userTags: [{ username: "@jane", x: "0.25", y: "0.8" }],
        productTags: "p1, p2",
        locationId: "  42  ",
      }),
    ).toEqual({
      userTags: [{ username: "jane", x: 0.25, y: 0.8 }],
      productTags: ["p1", "p2"],
      locationId: "42",
    })
  })

  it("drops user tags with out-of-range coordinates or no username", () => {
    expect(
      cleanPostTypeMeta("instagram_stories", {
        userTags: [
          { username: "ok", x: 0.1, y: 0.1 },
          { username: "bad", x: 1.5, y: 0.2 },
          { username: "", x: 0.2, y: 0.2 },
        ],
      }),
    ).toEqual({ userTags: [{ username: "ok", x: 0.1, y: 0.1 }] })
  })

  it("parses instagram reels audio name and location", () => {
    expect(
      cleanPostTypeMeta("instagram_reels", {
        audioName: "  Lofi beats ",
        locationId: "99",
      }),
    ).toEqual({ audioName: "Lofi beats", locationId: "99" })
  })

  it("caps instagram reels collaborators at 3, leaves facebook reels unbounded", () => {
    expect(
      cleanPostTypeMeta("instagram_reels", {
        collaborators: "@a, @b, @c, @d",
      }),
    ).toEqual({ collaborators: ["a", "b", "c"] })

    expect(
      cleanPostTypeMeta("facebook_page_reels", {
        collaborators: "a, b, c, d",
      }),
    ).toEqual({ collaborators: ["a", "b", "c", "d"] })
  })

  it("parses youtube custom thumbnail url and madeForKids", () => {
    expect(
      cleanPostTypeMeta("youtube_video", {
        customThumbnailUrl: "https://cdn.example.com/thumb.jpg",
        madeForKids: true,
      }),
    ).toEqual({
      customThumbnailUrl: "https://cdn.example.com/thumb.jpg",
      madeForKids: true,
    })
  })

  it("rejects a non-https youtube custom thumbnail url", () => {
    expect(() =>
      cleanPostTypeMeta("youtube_shorts", { customThumbnailUrl: "ftp://nope" }),
    ).toThrow()
  })

  it("keeps a valid linkedin visibility and drops invalid", () => {
    expect(
      cleanPostTypeMeta("linkedin_personal", { visibility: "connections" }),
    ).toEqual({ visibility: "connections" })

    expect(() =>
      cleanPostTypeMeta("linkedin_organization", {
        organizationUrn: "urn:li:organization:1234567",
        visibility: "everyone",
      }),
    ).toThrow()
  })
})
