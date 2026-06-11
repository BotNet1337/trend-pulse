/**
 * extractErrorMessage — maps an axios-style error to a localised user-facing string.
 *
 * Shared between PacksBlock (component) and packs-api.spec.ts (unit test) so that
 * the logic lives in one place and tests are not tautological copies of the source.
 */

/** Shape of the unified error envelope (TASK-030). */
interface ErrorData {
  error?: { message?: string };
  detail?: string;
}

/** Extract a user-friendly error message from an axios-style error. */
export function extractErrorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const e = error as { response?: { status?: number; data?: ErrorData } };
    if (e.response?.status === 402) {
      // Read envelope message first (TASK-030), fall back to legacy {detail}.
      const detail = e.response?.data?.error?.message ?? e.response?.data?.detail;
      return detail
        ? `Pack limit reached: ${detail}`
        : 'You have reached the pack limit on your current plan. Upgrade your plan to add more.';
    }
    if (e.response?.status === 404) {
      return 'Pack not found.';
    }
  }
  // Verbatim GENERIC_ERROR_MESSAGE (shared/api/client.ts) — single error voice.
  return 'Something went wrong. Please try again.';
}
