/**
 * Telegram channel handle format utilities — shared constant used by both
 * client-side pre-validation (instant feedback) and as a reference in tests.
 *
 * Source of truth for correctness is always the backend (422 response).
 * This regex provides UX-level fast feedback only; never treat it as the
 * authoritative validator.
 *
 * Format: @username — @ required, 5-32 alphanumeric/underscore chars.
 * Reference: https://core.telegram.org/method/account.checkUsername
 */

/** Shared regex for Telegram handle pre-validation (UX only, not authoritative). */
export const HANDLE_REGEX = /^@[A-Za-z0-9_]{5,32}$/;

/** Human-readable hint shown below the handle field. */
export const HANDLE_FORMAT_HINT =
  'Must start with @ followed by 5–32 letters, numbers, or underscores (e.g. @mychannel)';

/**
 * Client-side pre-validation of a Telegram channel handle.
 * Returns null if valid, or a user-facing error string if invalid.
 * This is UX-only — backend 422 is the authoritative gate.
 */
export function validateHandleFormat(handle: string): string | null {
  if (!handle) return 'Channel handle is required';
  if (!HANDLE_REGEX.test(handle)) return HANDLE_FORMAT_HINT;
  return null;
}
