/**
 * extractApiKeysErrorMessage — maps an axios-style error to a user-facing
 * EN string (TASK-065; pattern: features/packs/error-message.ts).
 *
 * 403 = server-side plan gate (`assert_within_limit`, PLAN_LIMIT_EXCEEDED,
 * TASK-028) → Trader upsell. 404 = key already gone (revoked elsewhere).
 * 422 = name validation from the backend.
 */

/** Shape of the unified error envelope (TASK-030). */
interface ErrorData {
  error?: { code?: string; message?: string };
  detail?: string;
}

const TRADER_GATE_MESSAGE =
  'API access is available on the Trader plan. Upgrade to create API keys.';
const KEY_NOT_FOUND_MESSAGE =
  'API key not found. It may have been revoked in another session.';
const INVALID_NAME_MESSAGE = 'Please enter a valid key name.';
// Verbatim GENERIC_ERROR_MESSAGE (shared/api/client.ts) — single error voice.
const GENERIC_MESSAGE = 'Something went wrong. Please try again.';

/** Extract a user-friendly error message from an axios-style error. */
export function extractApiKeysErrorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const e = error as { response?: { status?: number; data?: ErrorData } };
    const status = e.response?.status;
    if (status === 403) {
      // Plan gate: fixed upsell copy — do not surface the raw backend detail.
      return TRADER_GATE_MESSAGE;
    }
    if (status === 404) {
      return KEY_NOT_FOUND_MESSAGE;
    }
    if (status === 422) {
      // Envelope message first (TASK-030), fall back to legacy {detail}.
      const detail = e.response?.data?.error?.message ?? e.response?.data?.detail;
      return detail ?? INVALID_NAME_MESSAGE;
    }
  }
  return GENERIC_MESSAGE;
}
