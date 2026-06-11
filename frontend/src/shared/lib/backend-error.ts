/**
 * Backend error mapping — maps API error-envelope (TASK-030) responses into
 * UX-state discriminated unions.
 *
 * Primary discriminator: `error.code` from the unified envelope
 *   {"error": {"code": "<ErrorCode>", "message": str, "details?": [...]}}
 *
 * Legacy fallback: when the envelope is absent (old proxy / CDN response returns
 * `{"detail": ...}`) the mapping falls back to HTTP status code discrimination.
 *
 * Used by features/watchlists mutations and any other caller that needs to
 * translate API errors into typed UI states.
 */

import type { AxiosError } from 'axios';

/** Pydantic-normalised field error item from the VALIDATION envelope. */
export interface ValidationDetailItem {
  field: string;
  message: string;
}

/**
 * Legacy Pydantic FastAPI validation error detail item shape (pre-TASK-030).
 * Still accepted by parseValidationFields for backward-compat with proxy responses.
 */
export interface LegacyValidationDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** Discriminated union — one variant per UX state. */
export type BackendErrorState =
  | { kind: 'unauthorized'; message: string }     // UNAUTHORIZED — auth required
  | { kind: 'quota'; message: string }             // PLAN_LIMIT_EXCEEDED (402)
  | { kind: 'feature-gate'; message: string }      // FEATURE_NOT_AVAILABLE (403)
  | { kind: 'forbidden'; message: string }         // FORBIDDEN (403, non-plan)
  | { kind: 'not-found'; message: string }         // NOT_FOUND (404)
  | { kind: 'duplicate'; message: string }         // DUPLICATE (409)
  | { kind: 'field'; fields: Record<string, string>; message: string } // VALIDATION (422)
  | { kind: 'rate-limited'; message: string }      // RATE_LIMITED (429)
  | { kind: 'billing-not-configured'; message: string } // BILLING_NOT_CONFIGURED (503)
  | { kind: 'generic'; message: string };          // anything else (INTERNAL, unknown)

const DEFAULT_MESSAGES: Record<string, string> = {
  unauthorized:
    'You are not signed in. Please sign in to continue.',
  quota:
    'You have reached the watchlist limit for your current plan. Upgrade to add more.',
  'feature-gate':
    'This feature is not available on your current plan. Upgrade to unlock it.',
  forbidden:
    'You do not have permission to perform this action.',
  'not-found': 'Watchlist not found or you do not have access to it.',
  duplicate:
    'A watchlist for this channel and topic already exists.',
  'rate-limited': 'Too many requests. Please slow down.',
  'billing-not-configured': 'Billing service is not configured. Please contact support.',
  generic: 'Something went wrong. Please try again.',
};

/** Shape of the unified error envelope (TASK-030). */
interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: ValidationDetailItem[];
  };
  /** Legacy field from pre-TASK-030 responses. */
  detail?: unknown;
}

function getResponseData(error: AxiosError): ErrorEnvelope | undefined {
  return error.response?.data as ErrorEnvelope | undefined;
}

/** Extract the error code from the envelope (primary discriminator). */
function extractCode(error: AxiosError): string | undefined {
  return getResponseData(error)?.error?.code;
}

/** Extract message from envelope or legacy detail. */
function extractMessage(error: AxiosError): string {
  const data = getResponseData(error);
  // Prefer envelope message
  const envelopeMsg = data?.error?.message;
  if (typeof envelopeMsg === 'string' && envelopeMsg) return envelopeMsg;
  // Legacy fallback: {detail: str}
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  return error.message || DEFAULT_MESSAGES.generic;
}

/**
 * Parse field errors from the envelope `details` array (primary) or from the
 * legacy Pydantic `detail` array (fallback).
 */
function parseFieldErrors(error: AxiosError): Record<string, string> {
  const data = getResponseData(error);
  const fields: Record<string, string> = {};

  // Primary: envelope details[{field, message}] (TASK-030 normalised)
  const details = data?.error?.details;
  if (Array.isArray(details) && details.length > 0) {
    for (const item of details as ValidationDetailItem[]) {
      const key = item.field || 'root';
      fields[key] = item.message;
    }
    return fields;
  }

  // Legacy fallback: Pydantic [{loc, msg, type}] under "detail"
  const legacyDetail = data?.detail;
  if (Array.isArray(legacyDetail)) {
    for (const item of legacyDetail as LegacyValidationDetail[]) {
      const key = (item.loc ?? [])
        .filter((p) => p !== 'body')
        .join('.')
        .replace(/\.\d+\./g, '.')
        .replace(/^\d+\./, '');
      const fieldKey = key || 'root';
      fields[fieldKey] = item.msg;
    }
  }
  return fields;
}

/**
 * Map an error code (ErrorCode StrEnum value) to a BackendErrorState kind.
 * Returns undefined when the code is unknown (falls back to HTTP status).
 */
function codeToKind(code: string): BackendErrorState['kind'] | undefined {
  switch (code) {
    case 'UNAUTHORIZED':
      return 'unauthorized';
    case 'PLAN_LIMIT_EXCEEDED':
      return 'quota';
    case 'FEATURE_NOT_AVAILABLE':
      return 'feature-gate';
    case 'FORBIDDEN':
      return 'forbidden';
    case 'NOT_FOUND':
      return 'not-found';
    case 'DUPLICATE':
      return 'duplicate';
    case 'VALIDATION':
      return 'field';
    case 'RATE_LIMITED':
      return 'rate-limited';
    case 'BILLING_NOT_CONFIGURED':
      return 'billing-not-configured';
    case 'INTERNAL':
      return 'generic';
    default:
      return undefined;
  }
}

/**
 * Map an HTTP status to a BackendErrorState kind (legacy fallback only).
 * Used when the response lacks an error envelope (old proxy / CDN response).
 */
function statusToKind(status: number | undefined): BackendErrorState['kind'] {
  switch (status) {
    case 401:
      return 'unauthorized';
    case 402:
      return 'quota';
    case 403:
      return 'feature-gate';
    case 404:
      return 'not-found';
    case 409:
      return 'duplicate';
    case 422:
      return 'field';
    case 429:
      return 'rate-limited';
    case 503:
      return 'billing-not-configured';
    default:
      return 'generic';
  }
}

/**
 * Map an AxiosError from an API call into a typed UX state.
 *
 * Primary: discriminates by `error.code` from the unified envelope (TASK-030).
 * Fallback: HTTP status code (legacy proxy/CDN responses without envelope).
 */
export function mapBackendError(error: unknown): BackendErrorState {
  const axiosError = error as AxiosError;
  const status = axiosError.response?.status;

  // --- Primary path: envelope error.code ---
  const code = extractCode(axiosError);
  const kind: BackendErrorState['kind'] = code
    ? (codeToKind(code) ?? statusToKind(status))
    : statusToKind(status);

  const message = extractMessage(axiosError) || DEFAULT_MESSAGES[kind] || DEFAULT_MESSAGES.generic;

  if (kind === 'field') {
    const fields = parseFieldErrors(axiosError);
    return {
      kind,
      fields,
      message: Object.values(fields).join('. ') || message || 'Invalid input. Please check the fields.',
    };
  }

  return { kind, message } as BackendErrorState;
}
