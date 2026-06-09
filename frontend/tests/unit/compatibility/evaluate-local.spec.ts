/**
 * Unit tests for evaluateLocal — frontend local compatibility evaluator.
 *
 * Mirrors the backend CompatibilityService unit tests at:
 * apps/backend/tests/unit/compatibility/compatibility.service.spec.ts
 *
 * NULL probe fields (width, height, durationSec, codec) are treated as
 * "unknown — pass" to avoid false positives before Plan 1-02 backfills them.
 */
import { evaluateLocal } from "@/features/publications/compatibility/evaluate-local"
import { COMPATIBILITY_REASON_CODES } from "@/features/publications/compatibility/reason-codes"
import type {
  LocalEvaluateInput,
  MediaProbeInput,
  PlatformsCapabilitiesResponse,
} from "@/features/publications/compatibility/types"

// Minimal capabilities fixture — mirrors backend capability-matrix.ts
const CAPABILITIES: PlatformsCapabilitiesResponse = {
  platforms: [
    {
      postType: "instagram_feed",
      platform: "instagram",
      displayName: "Instagram Feed",
      image: {
        allowedMimes: ["image/jpeg", "image/png", "image/webp"],
        maxFileSizeBytes: 8 * 1024 * 1024,
        allowedAspectRatios: ["1:1", "4:5", "1.91:1"],
        maxWidth: 1080,
        minWidth: 320,
        maxHeight: null,
        maxDurationSec: null,
        allowedCodecs: null,
        mediaTypeRequired: "either",
      },
      video: {
        allowedMimes: ["video/mp4"],
        maxFileSizeBytes: 100 * 1024 * 1024,
        allowedAspectRatios: ["1:1", "4:5", "1.91:1"],
        maxWidth: 1920,
        minWidth: 320,
        maxHeight: null,
        maxDurationSec: 60,
        allowedCodecs: ["h264", "avc1"],
        mediaTypeRequired: "either",
      },
    },
    {
      postType: "instagram_reels",
      platform: "instagram",
      displayName: "Instagram Reels",
      image: null,
      video: {
        allowedMimes: ["video/mp4"],
        maxFileSizeBytes: 1 * 1024 * 1024 * 1024,
        allowedAspectRatios: ["9:16", "4:5"],
        maxWidth: 1080,
        minWidth: 500,
        maxHeight: null,
        maxDurationSec: 90,
        allowedCodecs: ["h264", "avc1"],
        mediaTypeRequired: "video",
      },
    },
    {
      postType: "linkedin_personal",
      platform: "linkedin",
      displayName: "LinkedIn Personal Post",
      image: {
        allowedMimes: ["image/jpeg", "image/png", "image/gif"],
        maxFileSizeBytes: 5 * 1024 * 1024,
        allowedAspectRatios: null,
        maxWidth: 4096,
        minWidth: null,
        maxHeight: null,
        maxDurationSec: null,
        allowedCodecs: null,
        mediaTypeRequired: "either",
      },
      video: {
        allowedMimes: ["video/mp4"],
        maxFileSizeBytes: 200 * 1024 * 1024,
        allowedAspectRatios: null,
        maxWidth: 1920,
        minWidth: null,
        maxHeight: null,
        maxDurationSec: 600,
        allowedCodecs: ["h264", "avc1"],
        mediaTypeRequired: "either",
      },
    },
  ],
}

const makeMedia = (overrides: Partial<MediaProbeInput> = {}): MediaProbeInput => ({
  mimeType: "image/jpeg",
  fileSizeBytes: 1024 * 1024,
  width: null,
  height: null,
  durationSec: null,
  codec: null,
  ...overrides,
})

const makeInput = (
  overrides: Partial<LocalEvaluateInput> = {},
): LocalEvaluateInput => ({
  postType: "instagram_feed",
  mediaItems: [makeMedia()],
  capabilities: CAPABILITIES,
  ...overrides,
})

describe("evaluateLocal()", () => {
  it("returns compatible=true for a valid JPEG on Instagram Feed", () => {
    const result = evaluateLocal(makeInput())
    expect(result.compatible).toBe(true)
    expect(result.issues).toHaveLength(0)
  })

  it("returns MIME_NOT_SUPPORTED for HEIC on LinkedIn Personal", () => {
    const result = evaluateLocal(
      makeInput({
        postType: "linkedin_personal",
        mediaItems: [makeMedia({ mimeType: "image/heic" })],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.MIME_NOT_SUPPORTED)
  })

  it("returns compatible=true for 60s mp4 on Instagram Feed (at boundary)", () => {
    const result = evaluateLocal(
      makeInput({
        mediaItems: [
          makeMedia({ mimeType: "video/mp4", durationSec: 60, fileSizeBytes: 10 * 1024 * 1024 }),
        ],
      }),
    )
    expect(result.compatible).toBe(true)
  })

  it("returns DURATION_EXCEEDED for 100s video on Instagram Feed (max 60s)", () => {
    const result = evaluateLocal(
      makeInput({
        mediaItems: [
          makeMedia({ mimeType: "video/mp4", durationSec: 100, fileSizeBytes: 10 * 1024 * 1024 }),
        ],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.DURATION_EXCEEDED)
  })

  it("returns FILE_SIZE_EXCEEDED for 9 MB image on LinkedIn (max 5 MB)", () => {
    const result = evaluateLocal(
      makeInput({
        postType: "linkedin_personal",
        mediaItems: [
          makeMedia({ mimeType: "image/jpeg", fileSizeBytes: 9 * 1024 * 1024 }),
        ],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.FILE_SIZE_EXCEEDED)
  })

  it("returns MEDIA_TYPE_NOT_SUPPORTED for image on Instagram Reels (video-only)", () => {
    const result = evaluateLocal(
      makeInput({
        postType: "instagram_reels",
        mediaItems: [makeMedia({ mimeType: "image/jpeg" })],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.MEDIA_TYPE_NOT_SUPPORTED)
  })

  it("returns compatible=true for 1:1 video on Instagram Feed (valid aspect ratio)", () => {
    const result = evaluateLocal(
      makeInput({
        mediaItems: [
          makeMedia({
            mimeType: "video/mp4",
            width: 1080,
            height: 1080,
            durationSec: 30,
            fileSizeBytes: 10 * 1024 * 1024,
          }),
        ],
      }),
    )
    expect(result.compatible).toBe(true)
  })

  it("returns ASPECT_RATIO_NOT_SUPPORTED for 16:9 video on Instagram Feed", () => {
    const result = evaluateLocal(
      makeInput({
        mediaItems: [
          makeMedia({
            mimeType: "video/mp4",
            width: 1920,
            height: 1080,
            durationSec: 30,
            fileSizeBytes: 10 * 1024 * 1024,
          }),
        ],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.ASPECT_RATIO_NOT_SUPPORTED)
  })

  it("returns CODEC_NOT_SUPPORTED for vp9 codec on Instagram Feed", () => {
    const result = evaluateLocal(
      makeInput({
        mediaItems: [
          makeMedia({
            mimeType: "video/mp4",
            width: 1080,
            height: 1080,
            durationSec: 30,
            fileSizeBytes: 10 * 1024 * 1024,
            codec: "vp9",
          }),
        ],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.CODEC_NOT_SUPPORTED)
  })

  it("returns compatible=true when width/height/durationSec/codec are all null (unknown = pass)", () => {
    const result = evaluateLocal(
      makeInput({
        mediaItems: [
          makeMedia({
            mimeType: "video/mp4",
            width: null,
            height: null,
            durationSec: null,
            codec: null,
            fileSizeBytes: 10 * 1024 * 1024,
          }),
        ],
      }),
    )
    expect(result.compatible).toBe(true)
  })

  it("returns compatible=true for unknown postType (passes through, backend validates)", () => {
    const result = evaluateLocal(
      makeInput({
        postType: "youtube_video" as "instagram_feed", // not in fixture caps
      }),
    )
    expect(result.compatible).toBe(true)
    expect(result.issues).toHaveLength(0)
  })

  it("returns RESOLUTION_TOO_LOW for underwidth image on Instagram Reels (min 500px)", () => {
    const result = evaluateLocal(
      makeInput({
        postType: "instagram_reels",
        mediaItems: [
          makeMedia({
            mimeType: "video/mp4",
            width: 400,
            height: 711,
            fileSizeBytes: 10 * 1024 * 1024,
          }),
        ],
      }),
    )
    expect(result.compatible).toBe(false)
    const codes = result.issues.map((i) => i.reasonCode)
    expect(codes).toContain(COMPATIBILITY_REASON_CODES.RESOLUTION_TOO_LOW)
  })
})
