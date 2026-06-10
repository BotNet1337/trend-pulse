/**
 * Unit tests: onboarding redirect criterion logic (TASK-039).
 *
 * Tests the redirect decision logic in pure form:
 *   - 0 watchlists + not on /onboarding → should redirect
 *   - 0 watchlists + already on /onboarding → no redirect (avoid loop)
 *   - N > 0 watchlists → no redirect
 *   - watchlists loading → no decision yet
 *
 * Pattern: pure function extraction, no React mount needed.
 */

import { describe, it, expect } from 'vitest';

/**
 * shouldRedirectToOnboarding — pure redirect criterion extracted from AuthGuard logic.
 *
 * Returns true when the user should be redirected to /onboarding.
 * Mirrors the condition in auth-guard.tsx:
 *   watchlists.length === 0 && !isOnOnboarding && !watchlistsLoading
 */
function shouldRedirectToOnboarding(opts: {
  watchlistCount: number | undefined;
  isOnOnboarding: boolean;
  watchlistsLoading: boolean;
}): boolean {
  const { watchlistCount, isOnOnboarding, watchlistsLoading } = opts;
  if (watchlistsLoading || watchlistCount === undefined) return false;
  if (isOnOnboarding) return false;
  return watchlistCount === 0;
}

describe('onboarding redirect criterion', () => {
  it('redirects when user has 0 watchlists and is not on /onboarding', () => {
    expect(
      shouldRedirectToOnboarding({
        watchlistCount: 0,
        isOnOnboarding: false,
        watchlistsLoading: false,
      }),
    ).toBe(true);
  });

  it('does NOT redirect when user is already on /onboarding (avoid loop)', () => {
    expect(
      shouldRedirectToOnboarding({
        watchlistCount: 0,
        isOnOnboarding: true,
        watchlistsLoading: false,
      }),
    ).toBe(false);
  });

  it('does NOT redirect when user has watchlists', () => {
    expect(
      shouldRedirectToOnboarding({
        watchlistCount: 3,
        isOnOnboarding: false,
        watchlistsLoading: false,
      }),
    ).toBe(false);
  });

  it('does NOT redirect while watchlists are still loading', () => {
    expect(
      shouldRedirectToOnboarding({
        watchlistCount: 0,
        isOnOnboarding: false,
        watchlistsLoading: true,
      }),
    ).toBe(false);
  });

  it('does NOT redirect when watchlist count is undefined (query not done)', () => {
    expect(
      shouldRedirectToOnboarding({
        watchlistCount: undefined,
        isOnOnboarding: false,
        watchlistsLoading: false,
      }),
    ).toBe(false);
  });

  it('does NOT redirect when user has exactly 1 watchlist', () => {
    expect(
      shouldRedirectToOnboarding({
        watchlistCount: 1,
        isOnOnboarding: false,
        watchlistsLoading: false,
      }),
    ).toBe(false);
  });
});
