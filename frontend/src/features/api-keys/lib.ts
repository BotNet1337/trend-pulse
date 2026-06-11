/**
 * Pure helpers for the api-keys feature (TASK-065) — unit-testable in node env.
 */

import type { ApiKeyRead } from './api';

/** Mirrors ApiKeyCreate.name minLength (openapi.json / api_keys/constants.py). */
export const API_KEY_NAME_MIN_LEN = 1;
/** Mirrors ApiKeyCreate.name maxLength (openapi.json / api_keys/constants.py). */
export const API_KEY_NAME_MAX_LEN = 255;

const NAME_REQUIRED_MESSAGE = 'Key name is required.';
const NAME_TOO_LONG_MESSAGE = `Key name must be ${API_KEY_NAME_MAX_LEN} characters or fewer.`;

/**
 * Client-side mirror of the OpenAPI name bounds.
 * Returns an EN error message, or null when the name is valid.
 * UX layer only — the server re-validates (422).
 */
export function validateApiKeyName(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length < API_KEY_NAME_MIN_LEN) return NAME_REQUIRED_MESSAGE;
  if (trimmed.length > API_KEY_NAME_MAX_LEN) return NAME_TOO_LONG_MESSAGE;
  return null;
}

/** A key is revoked when the backend set `revoked_at` (soft-revoke, TASK-028). */
export function isApiKeyRevoked(key: Pick<ApiKeyRead, 'revoked_at'>): boolean {
  return key.revoked_at !== null;
}

/** Format an ISO timestamp for display; em-dash for null (e.g. never used). */
export function formatApiKeyDate(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}
