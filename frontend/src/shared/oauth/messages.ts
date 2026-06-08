import { z } from "zod"

/**
 * postMessage envelope used by the OAuth popup pages
 * (`ChannelConnectedPage`, `ChannelConnectFailedPage`) to relay results to
 * the opener tab.
 *
 * SECURITY (TASK-AUDIT-RELEASE-1 / C6):
 * The opener already filters by `event.origin === window.location.origin`,
 * but `event.data` itself is untrusted (an extension or a same-origin tab
 * could fire malformed payloads). This schema is the type/shape contract;
 * use `oauthResultMessageSchema.safeParse(event.data)` on receive.
 *
 * The platform whitelist matches `entities/platform/PLATFORM_META`.
 */
export const oauthPlatformSchema = z.enum([
  "instagram",
  "facebook",
  "youtube",
  "linkedin",
])

export const oauthResultMessageSchema = z.discriminatedUnion("status", [
  z.object({
    type: z.literal("oauth-result"),
    status: z.literal("success"),
    workspaceId: z.string().uuid(),
    channelId: z.string().uuid(),
  }),
  z.object({
    type: z.literal("oauth-result"),
    status: z.literal("error"),
    reason: z.string(),
    platform: z.string(),
  }),
])

export type OAuthResultMessage = z.infer<typeof oauthResultMessageSchema>
