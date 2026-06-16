/**
 * Unit tests: TASK-120 revive/add UX helpers + pool-health invalidation.
 *
 * @testing-library/react is NOT installed (vitest env: node) — following the project
 * convention we test the pure view-model helpers and the query wiring directly:
 *  - asReviveOutcome narrowing (revive/add, unknown/absent → null)
 *  - reviveSuccessMessage: distinct re-connect vs add copy, names the label
 *  - invalidatePoolHealth invalidates exactly POOL_HEALTH_QUERY_KEY
 *
 * (accountLabel is covered authoritatively in lib.spec.ts — single source of truth.)
 */

import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

import {
  asReviveOutcome,
  reviveSuccessMessage,
} from '../../../src/features/pool-admin/lib';
import {
  POOL_HEALTH_QUERY_KEY,
  invalidatePoolHealth,
} from '../../../src/features/pool-admin/queries';

describe('asReviveOutcome', () => {
  it('narrows the known outcomes', () => {
    expect(asReviveOutcome('revive')).toBe('revive');
    expect(asReviveOutcome('add')).toBe('add');
  });

  it('maps absent/unknown to null (neutral, no wrong claim)', () => {
    expect(asReviveOutcome(null)).toBeNull();
    expect(asReviveOutcome(undefined)).toBeNull();
    expect(asReviveOutcome('')).toBeNull();
    expect(asReviveOutcome('whatever')).toBeNull();
  });
});

describe('reviveSuccessMessage', () => {
  it('says re-connected (same account) for a revive, names the label, leads with auto-pickup', () => {
    const msg = reviveSuccessMessage('revive', '@alice');
    expect(msg).toContain('Re-connected');
    expect(msg).toContain('@alice');
    expect(msg).toContain('same account');
    // No manual copy step in the face: lead with automatic pickup (fix/pool-live-pickup).
    expect(msg).toContain('automatically');
    expect(msg).not.toContain('Copy the session');
  });

  it('says added for an add, names the label, leads with auto-pickup (no copy step)', () => {
    const msg = reviveSuccessMessage('add', '@bob');
    expect(msg).toContain('Added');
    expect(msg).toContain('@bob');
    expect(msg).toContain('automatically');
    expect(msg).not.toContain('Copy the session');
  });

  it('falls back to a neutral success line when the outcome is null (no copy headline)', () => {
    const msg = reviveSuccessMessage(null, '@x');
    expect(msg).toContain('Logged in');
    // No revive/add claim when persistence outcome is unknown.
    expect(msg).not.toContain('Re-connected');
    expect(msg).not.toContain('Added');
    // The null case is a persistence FAILURE — must not tell the user to copy a string.
    expect(msg).not.toContain('Copy the session');
  });

  it('omits the label gracefully when none is provided', () => {
    expect(reviveSuccessMessage('revive', null)).toContain('Re-connected');
    expect(reviveSuccessMessage('add', undefined)).toContain('Added');
  });
});

describe('invalidatePoolHealth', () => {
  it('invalidates exactly the pool-health query key', async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, 'invalidateQueries');

    await invalidatePoolHealth(client);

    expect(spy).toHaveBeenCalledWith({ queryKey: POOL_HEALTH_QUERY_KEY });
  });
});
