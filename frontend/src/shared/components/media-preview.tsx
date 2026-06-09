import * as React from "react"

import { cn } from "@/shared/utils/index"

type MediaKind = "image" | "video"

export interface MediaPreviewProps {
  src?: string
  mimeType?: string
  /** Override mime-based detection. */
  kind?: MediaKind
  alt?: string
  className?: string
  loading?: "lazy" | "eager"
  /** Object-fit utility — defaults to `object-cover`. */
  fit?: string
}

const isVideoMime = (mime: string | undefined): boolean =>
  typeof mime === "string" && mime.startsWith("video/")

/**
 * Image / video thumbnail that fades in once the asset has decoded. Lets the
 * parent's placeholder (gradient, skeleton, solid bg) stay visible during the
 * load instead of flashing the swap.
 *
 * Video gets a "first-frame as poster" nudge: on `loadedmetadata` we seek to
 * 0.001s so the browser actually paints the first frame — without this most
 * browsers leave the element black until the user hovers / plays.
 */
export const MediaPreview: React.FC<MediaPreviewProps> = ({
  src,
  mimeType,
  kind,
  alt = "",
  className,
  loading = "lazy",
  fit = "object-cover",
}) => {
  const resolvedKind: MediaKind =
    kind ?? (isVideoMime(mimeType) ? "video" : "image")
  const [loaded, setLoaded] = React.useState(false)
  const imgRef = React.useRef<HTMLImageElement | null>(null)

  // Reset on src change so the next asset gets a fresh fade-in instead of
  // inheriting a stale `loaded=true`.
  React.useEffect(() => {
    setLoaded(false)
  }, [src])

  // Cached image: onLoad may have fired before React attached the handler.
  // `complete && naturalWidth > 0` is the canonical readiness probe.
  React.useEffect(() => {
    if (resolvedKind !== "image") return
    const el = imgRef.current
    if (el && el.complete && el.naturalWidth > 0) setLoaded(true)
  }, [src, resolvedKind])

  if (!src) return null

  const mediaClass = cn(
    "absolute inset-0 h-full w-full transition-opacity duration-300",
    fit,
    loaded ? "opacity-100" : "opacity-0",
    className,
  )

  if (resolvedKind === "video") {
    return (
      <video
        src={src}
        className={mediaClass}
        muted
        playsInline
        preload="metadata"
        onLoadedMetadata={(event) => {
          const el = event.currentTarget
          if (el.currentTime === 0) {
            try {
              el.currentTime = 0.001
            } catch {
              // Some browsers reject the seek on cross-origin video without
              // anonymous CORS — opacity stays 0 and the gradient shows
              // through, which is preferable to a black flash.
            }
          }
        }}
        onLoadedData={() => setLoaded(true)}
        onSeeked={() => setLoaded(true)}
      />
    )
  }

  return (
    <img
      ref={imgRef}
      src={src}
      alt={alt}
      loading={loading}
      decoding="async"
      className={mediaClass}
      onLoad={() => setLoaded(true)}
    />
  )
}
