import { describe, expect, it } from 'vitest';

import {
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
