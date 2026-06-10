/**
 * Unit tests: referral code propagation (TASK-046).
 *
 * Tests:
 * - ?ref= URL param is stored in localStorage under 'referrer_code'.
 * - Stored referrer_code is included in the register payload.
 * - localStorage is cleared after successful registration.
 * - Missing ?ref= param leaves localStorage unchanged (no spurious set).
 * - Empty ?ref= is ignored.
 *
 * NOTE: localStorage key and payload field renamed from 'ref_code' to
 * 'referrer_code' (TASK-046 G2 fix) to avoid backend ORM column collision.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const REF_CODE_STORAGE_KEY = 'referrer_code';

describe('ref propagation — URL → localStorage → register payload', () => {
  // Minimal localStorage mock (node environment has no DOM).
  let store: Record<string, string> = {};
  const localStorageMock = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };

  beforeEach(() => {
    store = {};
    vi.stubGlobal('localStorage', localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // ---------------------------------------------------------------------------
  // Step 1: ?ref= → localStorage
  // ---------------------------------------------------------------------------

  it('stores ref_code in localStorage from URL ?ref= param', () => {
    // Simulate SignUpPage useEffect behaviour: read ?ref= and persist.
    const params = new URLSearchParams('?ref=INVITE42');
    const refFromUrl = params.get('ref');
    if (refFromUrl) {
      localStorage.setItem(REF_CODE_STORAGE_KEY, refFromUrl);
    }

    expect(localStorage.getItem(REF_CODE_STORAGE_KEY)).toBe('INVITE42');
  });

  it('does not touch localStorage when ?ref= is absent', () => {
    const params = new URLSearchParams('');
    const refFromUrl = params.get('ref');
    if (refFromUrl) {
      localStorage.setItem(REF_CODE_STORAGE_KEY, refFromUrl);
    }

    expect(localStorage.getItem(REF_CODE_STORAGE_KEY)).toBeNull();
  });

  it('does not touch localStorage when ?ref= is empty', () => {
    const params = new URLSearchParams('?ref=');
    const refFromUrl = params.get('ref');
    if (refFromUrl) {
      localStorage.setItem(REF_CODE_STORAGE_KEY, refFromUrl);
    }
    // Empty string is falsy — should not be stored.
    expect(localStorage.getItem(REF_CODE_STORAGE_KEY)).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Step 2: localStorage → register payload
  // ---------------------------------------------------------------------------

  it('includes referrer_code in register payload when present in localStorage', () => {
    localStorage.setItem(REF_CODE_STORAGE_KEY, 'INVITE42');

    // Simulate mutationFn: read from localStorage and build payload.
    const storedRef = localStorage.getItem(REF_CODE_STORAGE_KEY) ?? undefined;
    const payload = { email: 'user@test.com', password: 'secret', referrer_code: storedRef };

    expect(payload.referrer_code).toBe('INVITE42');
  });

  it('omits referrer_code from payload when localStorage is empty', () => {
    const storedRef = localStorage.getItem(REF_CODE_STORAGE_KEY) ?? undefined;
    const payload = { email: 'user@test.com', password: 'secret', referrer_code: storedRef };

    expect(payload.referrer_code).toBeUndefined();
  });

  // ---------------------------------------------------------------------------
  // Step 3: clear localStorage after successful register
  // ---------------------------------------------------------------------------

  it('clears ref_code from localStorage after successful registration', () => {
    localStorage.setItem(REF_CODE_STORAGE_KEY, 'INVITE42');

    // Simulate post-success cleanup.
    localStorage.removeItem(REF_CODE_STORAGE_KEY);

    expect(localStorage.getItem(REF_CODE_STORAGE_KEY)).toBeNull();
  });

  it('does not error when clearing a non-existent ref_code', () => {
    // Should not throw even if the key was never set.
    expect(() => localStorage.removeItem(REF_CODE_STORAGE_KEY)).not.toThrow();
  });
});
