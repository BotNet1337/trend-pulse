/**
 * Server API client spec — SSR prefetch baseURL versioning.
 *
 * Regression guard for the e2e ssr.spec.ts AC3 failure: backend mounts all
 * routes under /v1 (TASK-030 / ADR-007), and the SSR prefetch client talks to
 * the api service directly (no nginx /api/ → /v1 rewrite). The /v1 prefix must
 * therefore be appended to API_URL here — without it GET /users/me 404s and
 * hydration is silently dropped (__INITIAL_STATE__.user === null).
 */
import { describe, expect, it } from 'vitest';
import { versionedApiBaseUrl } from '../../../server/client';

describe('versionedApiBaseUrl', () => {
  it('appends /v1 to the API_URL', () => {
    expect(versionedApiBaseUrl('http://api:8000')).toBe('http://api:8000/v1');
  });

  it('strips trailing slashes before appending /v1', () => {
    expect(versionedApiBaseUrl('http://api:8000/')).toBe('http://api:8000/v1');
    expect(versionedApiBaseUrl('http://api:8000//')).toBe('http://api:8000/v1');
  });

  it('returns undefined when API_URL is not set', () => {
    expect(versionedApiBaseUrl(undefined)).toBeUndefined();
  });
});
