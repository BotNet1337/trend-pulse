import * as React from "react"

import { X } from "@/shared/images"
import { cn } from "@/shared/utils/index"

export interface MediaViewerItem {
  id: string
  url?: string
  mimeType?: string
}

export interface MediaViewerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  item: MediaViewerItem | null
}

const isVideoMime = (mime: string | undefined): boolean =>
  typeof mime === "string" && mime.startsWith("video/")

/**
 * Lightweight fullscreen viewer for a single image / video. Sits in the
 * shared layer so post media galleries, publication media galleries, and
 * the workspace preview can all reuse the same overlay.
 *
 * Behaviour:
 *  - ESC and backdrop click both close the viewer.
 *  - Videos render with native HTML5 controls and `autoPlay` so the user
 *    sees content immediately after the click.
 *  - Body scroll is frozen while the viewer is open so the page underneath
 *    doesn't drift.
 */
export const MediaViewerDialog: React.FC<MediaViewerDialogProps> = ({
  open,
  onOpenChange,
  item,
}) => {
  React.useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false)
    }
    document.addEventListener("keydown", handler)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", handler)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onOpenChange])

  if (!open || !item) return null

  const isVideo = isVideoMime(item.mimeType)

  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="media-viewer-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 sm:p-8"
      onClick={() => onOpenChange(false)}
    >
      <button
        type="button"
        aria-label="Close viewer"
        onClick={(event) => {
          event.stopPropagation()
          onOpenChange(false)
        }}
        className={cn(
          "absolute top-4 right-4 inline-flex cursor-pointer items-center justify-center size-10 rounded-full",
          "bg-black/50 text-white hover:bg-black/70 transition-colors",
        )}
      >
        <X className="size-5" />
      </button>
      <div
        className="relative max-h-full max-w-full"
        onClick={(event) => event.stopPropagation()}
      >
        {item.url ? (
          isVideo ? (
            <video
              src={item.url}
              controls
              autoPlay
              playsInline
              className="max-h-[90vh] max-w-[90vw] rounded-lg shadow-2xl"
            />
          ) : (
            <img
              src={item.url}
              alt=""
              className="max-h-[90vh] max-w-[90vw] rounded-lg shadow-2xl object-contain"
            />
          )
        ) : (
          <p className="text-white/80 text-sm">
            Media preview is not available for this item.
          </p>
        )}
      </div>
    </div>
  )
}
