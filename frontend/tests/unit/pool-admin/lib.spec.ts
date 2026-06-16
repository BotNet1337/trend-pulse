import { describe, expect, it } from 'vitest';

import {
  accountErrorExplanation,
  accountLabel,
  accountStateBadgeVariant,
  accountStateLabel,
  asAccountState,
  type AccountState,
} from '../../../src/features/pool-admin/lib';

describe('asAccountState', () => {
  it('narrows the known states including failing (TASK-118)', () => {
    const known: AccountState[] = ['healthy', 'cooling', 'quarantined', 'failing'];
    for (const state of known) {
      expect(asAccountState(state)).toBe(state);
    }
  });

  it('maps an unknown state to quarantined (fail-safe default)', () => {
    expect(asAccountState('totally-unknown')).toBe('quarantined');
  });
});

describe('accountStateLabel', () => {
  it('labels failing distinctly from quarantined', () => {
    expect(accountStateLabel('failing')).toBe('Failing');
    expect(accountStateLabel('quarantined')).toBe('Quarantined');
    expect(accountStateLabel('healthy')).toBe('Connected');
    expect(accountStateLabel('cooling')).toBe('Cooling');
  });
});

describe('accountStateBadgeVariant', () => {
  it('uses warning for failing (soft alert), danger for quarantined (dead)', () => {
    expect(accountStateBadgeVariant('failing')).toBe('warning');
    expect(accountStateBadgeVariant('quarantined')).toBe('danger');
    expect(accountStateBadgeVariant('healthy')).toBe('success');
    expect(accountStateBadgeVariant('cooling')).toBe('warning');
  });
});

describe('accountLabel', () => {
  it('prefers the @username display_label as the row identity', () => {
    expect(accountLabel('@hart_1337', 2)).toBe('@hart_1337');
  });

  it('trims surrounding whitespace on the display_label', () => {
    expect(accountLabel('  @hart_1337  ', 2)).toBe('@hart_1337');
  });

  it('falls back to #<index> when display_label is null/empty (env/legacy slot)', () => {
    expect(accountLabel(null, 0)).toBe('#0');
    expect(accountLabel(undefined, 3)).toBe('#3');
    expect(accountLabel('   ', 5)).toBe('#5');
  });
});

describe('accountErrorExplanation', () => {
  it('explains the SecurityError (wrong session ID) conflict in RU', () => {
    const text = accountErrorExplanation('SecurityError');
    expect(text).toContain('wrong session ID');
    expect(text.toLowerCase()).toContain('qr');
  });

  it('explains a dead-session class as "перевыпусти"', () => {
    for (const cls of [
      'AuthKeyDuplicatedError',
      'AuthKeyError',
      'SessionRevokedError',
      'UserDeactivatedError',
    ]) {
      expect(accountErrorExplanation(cls)).toContain('перевыпусти');
    }
  });

  it('explains a FLOOD_WAIT reason as a temporary Telegram limit', () => {
    expect(accountErrorExplanation('FLOOD_WAIT')).toContain('FLOOD_WAIT');
  });

  it('returns the raw class name for an unknown reason (no guessing)', () => {
    expect(accountErrorExplanation('SomeNovelTelethonError')).toBe('SomeNovelTelethonError');
  });

  it('returns null for an empty/absent reason (nothing to show)', () => {
    expect(accountErrorExplanation('')).toBeNull();
    expect(accountErrorExplanation(null)).toBeNull();
    expect(accountErrorExplanation(undefined)).toBeNull();
  });
});
