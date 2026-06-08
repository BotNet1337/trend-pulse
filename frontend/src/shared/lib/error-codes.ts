/**
 * Backend error codes mirrored from `apps/backend/src/modules/<module>/domain/errors`.
 * Update in lockstep when backend codes change.
 *
 * Ranges:
 *   IAM           — 10xxx
 *   Workspace     — 20xxx
 *   Content       — 30xxx
 *   Storage       — 30xxx (overlaps Content; keep STORAGE_ prefix)
 *   Channels      — 40xxx
 *   Dispatcher    — 50xxx
 *   Notifications — 60xxx
 */
export const ERROR_CODE_MESSAGES: Readonly<Record<number, string>> = {
  // IAM
  10001: "An account with this email already exists.",
  10002: "Invalid email or password.",
  10003: "Please verify your email before signing in.",
  10004: "Account not found.",
  10005: "Account already exists for this provider.",
  10006: "User not found.",
  10007: "Email format is invalid.",
  10008: "Password does not meet requirements.",
  10009: "This sign-in provider is not supported.",
  10010: "Email is already verified.",
  10011: "CAPTCHA verification failed. Please try again.",
  10012: "Authentication token is invalid or expired.",

  // Workspace
  20001: "Workspace not found.",
  20002: "You don't have access to this workspace.",
  20003: "Workspace name is invalid.",
  20004: "No default workspace exists for this account.",
  20005: "Workspace author is required.",

  // Content
  30001: "Post not found.",
  30002: "This post has already been published.",
  30003: "Publication not found.",
  30004: "Post is in a state that doesn't allow this action.",
  30005: "Media limit exceeded for this post.",
  30006: "Invalid state transition.",
  30007: "This publication already exists.",
  30008: "Publication media is missing.",
  30009: "Channel doesn't belong to this workspace.",
  30010: "Post doesn't belong to this workspace.",
  30011: "Post media not found.",
  30012: "Storage object is not accessible.",
  30013: "Invalid post type.",
  30014: "Post type is not supported by this platform.",

  // Channels
  40001: "Channel not found.",
  40003: "Channel connection failed during the OAuth callback.",
  40004: "Couldn't refresh the channel's access token. Please reconnect the channel.",
  40005: "This platform is not supported.",
  40006: "Channel access has expired. Reconnect to continue.",
  40007: "OAuth state is invalid or expired. Please try connecting again.",
  40008: "Channel data is corrupted.",
  40009: "Channel scope configuration is invalid.",
  40010: "Channel credentials are corrupted. Please reconnect the channel.",
  40011: "Channel doesn't belong to this workspace.",

  // Dispatcher
  50001: "Failed to dispatch the publication.",
  50002: "Platform returned an error while publishing.",
  50003: "Platform is not supported for publishing.",
  50004: "Channel is inactive.",
  50007: "Publication not found.",
  50008: "Planned publication not found.",
  50009: "This publication has already been planned.",
  50010: "Internal token is invalid.",
  50011: "Internal token is missing.",
  50012: "Channel access has expired.",
  50013: "Channel scopes are insufficient for publishing.",
  50014: "Platform validation failed.",
  50015: "Media is unavailable.",
  50016: "Service is temporarily unavailable. Please try again shortly.",
  50017: "Content type is not supported.",
  50018: "Media MIME type is not supported.",
  50019: "Publishing timed out. Please try again.",
  50020: "Failed to refresh credentials.",
  50021: "Rate limit exceeded. Please wait before retrying.",
  50022: "Media format is not supported by this platform.",

  // Notifications
  60001: "Email template not found.",
  60002: "Email template rendering failed.",
  60003: "Email delivery failed.",
  60004: "Notifications service is unavailable.",
  60005: "Email template already exists.",
  60006: "Email template is invalid.",
};

/**
 * Resolves a backend error response into a user-friendly message.
 * Falls back to the server-provided message, then to a generic copy.
 */
export const resolveErrorMessage = (
  code: number | undefined,
  fallback?: string,
): string => {
  if (code !== undefined && ERROR_CODE_MESSAGES[code]) {
    return ERROR_CODE_MESSAGES[code];
  }
  return fallback ?? "Something went wrong. Please try again.";
};
