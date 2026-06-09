/**
 * Backend error mapping — maps HTTP status codes from watchlist (and other)
 * API responses into UX-state discriminated unions.
 *
 * Used by features/watchlists mutations to translate 402/403/422/404/409
 * into typed states the UI components react to.
 *
 * Pattern: the mutation catches AxiosError, calls mapBackendError, and
 * the component switches on the returned kind to render the right UI.
 */

import type { AxiosError } from 'axios';

/** Pydantic FastAPI validation error detail item shape. */
export interface ValidationDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** Discriminated union — one variant per UX state. */
export type BackendErrorState =
  | { kind: 'quota'; message: string }          // 402 — plan limit exceeded → upsell
  | { kind: 'feature-gate'; message: string }   // 403 — feature not available on plan
  | { kind: 'field'; fields: Record<string, string>; message: string } // 422 — validation
  | { kind: 'not-found'; message: string }       // 404 — resource not found
  | { kind: 'duplicate'; message: string }       // 409 — duplicate (channel, topic)
  | { kind: 'generic'; message: string };        // anything else

const DEFAULT_MESSAGES: Record<string, string> = {
  quota:
    'You have reached the watchlist limit for your current plan. Upgrade to add more.',
  'feature-gate':
    'This feature is not available on your current plan. Upgrade to unlock it.',
  'not-found': 'Watchlist not found or you do not have access to it.',
  duplicate:
    'A watchlist for this channel and topic already exists.',
  generic: 'Something went wrong. Please try again.',
};

function extractDetail(error: AxiosError): unknown {
  return (error.response?.data as Record<string, unknown> | undefined)?.detail;
}

function extractMessage(error: AxiosError): string {
  const data = error.response?.data as Record<string, unknown> | undefined;
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  return error.message || DEFAULT_MESSAGES.generic;
}

function parseValidationFields(error: AxiosError): Record<string, string> {
  const detail = extractDetail(error);
  const fields: Record<string, string> = {};

  if (Array.isArray(detail)) {
    for (const item of detail as ValidationDetail[]) {
      const key = item.loc
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
 * Map an AxiosError from a watchlist API call into a typed UX state.
 *
 * 402 → quota (plan limit exceeded) → show upsell
 * 403 → feature-gate (feature not on plan) → show upgrade message
 * 422 → field validation error → highlight field
 * 404 → not-found → show not-found state
 * 409 → duplicate → show dup message
 * else → generic error
 */
export function mapBackendError(error: unknown): BackendErrorState {
  const axiosError = error as AxiosError;
  const status = axiosError.response?.status;

  switch (status) {
    case 402:
      return {
        kind: 'quota',
        message: extractMessage(axiosError) || DEFAULT_MESSAGES.quota,
      };

    case 403:
      return {
        kind: 'feature-gate',
        message: extractMessage(axiosError) || DEFAULT_MESSAGES['feature-gate'],
      };

    case 422: {
      const fields = parseValidationFields(axiosError);
      return {
        kind: 'field',
        fields,
        message:
          Object.values(fields).join('. ') ||
          extractMessage(axiosError) ||
          'Invalid input. Please check the fields.',
      };
    }

    case 404:
      return {
        kind: 'not-found',
        message: DEFAULT_MESSAGES['not-found'],
      };

    case 409:
      return {
        kind: 'duplicate',
        message: DEFAULT_MESSAGES.duplicate,
      };

    default:
      return {
        kind: 'generic',
        message: extractMessage(axiosError) || DEFAULT_MESSAGES.generic,
      };
  }
}
