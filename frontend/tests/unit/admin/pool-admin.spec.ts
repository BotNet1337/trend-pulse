/**
 * Unit tests: TG pool admin UI (TASK-117, TASK-136) — pure view-model helpers, API paths,
 * and query/poll options.
 *
 * @testing-library/react is NOT installed (vitest env: node) — following the
 * project convention (admin-metrics.spec.ts, packs-api.spec.ts) we test the
 * pure logic and request wiring directly, no React mount:
 *  - QR flow state machine: terminal vs pending status (the poll stop condition)
 *  - status narrowing (unknown → 'error') and human, reason-bearing messages
 *  - account state narrowing + badge variant + cooldown formatting
 *  - not-found guard decision (non-superuser OR API 403 → not-found)
 *  - api: correct paths (start POST, poll GET with encoded token, health GET)
 *  - poll query: stops (refetchInterval → false) once status is terminal
 *  - factory api: correct GET/POST paths for accounts, budget, trigger, relogin
 *  - factory query options: stable keys, retry:false, enabled gate
 *  - factory lib: state narrowing, labels, badge variants, probation countdown
 *  - factory register button: pure disabled/tooltip helpers (TASK-136)
 */

import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../src/shared/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import { apiClient } from '../../../src/shared/api/client';
import {
  getFactoryAccounts,
  getFactoryBudget,
  getPoolHealth,
  pollQrLogin,
  reloginFactory,
  startQrLogin,
  triggerFactory,
} from '../../../src/features/pool-admin/api';
import {
  FACTORY_ACCOUNTS_QUERY_KEY,
  FACTORY_BUDGET_QUERY_KEY,
  POOL_HEALTH_QUERY_KEY,
  factoryAccountsQueryOptions,
  factoryBudgetQueryOptions,
  poolHealthQueryOptions,
  qrLoginPollQueryKey,
  qrLoginPollQueryOptions,
} from '../../../src/features/pool-admin/queries';
import {
  asAccountSource,
  asAccountState,
  asFactoryAccountState,
  asQrLoginStatus,
  accountSourceBadgeVariant,
  accountSourceLabel,
  accountStateBadgeVariant,
  accountStateLabel,
  factoryRegisterDisabledTooltip,
  factoryStateBadgeVariant,
  factoryStateLabel,
  formatCooldown,
  formatProbationCountdown,
  isFactoryRegisterDisabled,
  isTerminalQrStatus,
  qrStatusMessage,
  shouldShowPoolAdminNotFound,
} from '../../../src/features/pool-admin/lib';
import type { FactoryBudget } from '../../../src/features/pool-admin/api';

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

// ─── api ──────────────────────────────────────────────────────────────────────

describe('pool-admin api', () => {
  it('startQrLogin POSTs /pool-admin/qr-login/start', async () => {
    const payload = { token: 't1', qr_url: 'tg://login?token=x', expires_at: 1, timeout_seconds: 300 };
    mockedPost.mockResolvedValueOnce({ data: payload });
    const result = await startQrLogin();
    expect(mockedPost).toHaveBeenCalledWith('/pool-admin/qr-login/start');
    expect(result).toEqual(payload);
  });

  it('pollQrLogin GETs the token path (url-encoded)', async () => {
    mockedGet.mockResolvedValueOnce({ data: { status: 'pending', expires_at: 1 } });
    await pollQrLogin('a/b');
    expect(mockedGet).toHaveBeenCalledWith('/pool-admin/qr-login/a%2Fb');
  });

  it('getPoolHealth GETs /pool-admin/pool-health', async () => {
    mockedGet.mockResolvedValueOnce({ data: { stale: true, accounts: [] } });
    await getPoolHealth();
    expect(mockedGet).toHaveBeenCalledWith('/pool-admin/pool-health');
  });
});

// ─── queries ────────────────────────────────────────────────────────────────────

describe('poolHealthQueryOptions', () => {
  it('uses the stable key, never retries, fetches only when enabled', () => {
    expect(POOL_HEALTH_QUERY_KEY).toEqual(['admin', 'pool-health']);
    const enabled = poolHealthQueryOptions(true);
    expect(enabled.queryKey).toEqual(POOL_HEALTH_QUERY_KEY);
    expect(enabled.retry).toBe(false);
    expect(enabled.enabled).toBe(true);
    expect(poolHealthQueryOptions(false).enabled).toBe(false);
  });
});

describe('qrLoginPollQueryOptions (poll stop condition)', () => {
  it('null token → disabled', () => {
    expect(qrLoginPollQueryOptions(null).enabled).toBe(false);
  });

  it('keys by token', () => {
    expect(qrLoginPollQueryKey('t1')).toEqual(['admin', 'qr-login', 't1']);
    expect(qrLoginPollQueryOptions('t1').queryKey).toEqual(['admin', 'qr-login', 't1']);
  });

  it('polls while pending and on first load, stops on terminal', () => {
    const opts = qrLoginPollQueryOptions('t1');
    // no data yet → poll
    expect(opts.refetchInterval({ state: { data: undefined } })).toBe(2000);
    // pending → keep polling
    expect(opts.refetchInterval({ state: { data: { status: 'pending' } } })).toBe(2000);
    // terminal statuses → stop
    for (const status of ['success', 'expired', 'password_needed', 'error']) {
      expect(opts.refetchInterval({ state: { data: { status } } })).toBe(false);
    }
  });
});

// ─── QR flow state machine ──────────────────────────────────────────────────────

describe('isTerminalQrStatus / asQrLoginStatus', () => {
  it('pending is the only non-terminal status', () => {
    expect(isTerminalQrStatus('pending')).toBe(false);
    expect(isTerminalQrStatus('success')).toBe(true);
    expect(isTerminalQrStatus('expired')).toBe(true);
    expect(isTerminalQrStatus('password_needed')).toBe(true);
    expect(isTerminalQrStatus('error')).toBe(true);
  });

  it('narrows known statuses and maps unknown → error', () => {
    expect(asQrLoginStatus('success')).toBe('success');
    expect(asQrLoginStatus('bogus')).toBe('error');
  });
});

describe('qrStatusMessage (specific reason, not generic)', () => {
  it('weaves the reason into password_needed / error', () => {
    expect(qrStatusMessage('error', 'FloodWaitError')).toContain('FloodWaitError');
    expect(qrStatusMessage('password_needed', 'SessionPasswordNeededError')).toContain(
      'SessionPasswordNeededError',
    );
  });

  it('has sensible defaults when reason is null', () => {
    expect(qrStatusMessage('error', null)).toMatch(/failed/i);
    expect(qrStatusMessage('expired', null)).toMatch(/expired/i);
    expect(qrStatusMessage('pending', null)).toMatch(/scan|authorize/i);
    expect(qrStatusMessage('success', null)).toMatch(/copy/i);
  });
});

// ─── account state / cooldown ───────────────────────────────────────────────────

describe('account state helpers', () => {
  it('narrows known states, unknown → quarantined (fail-safe)', () => {
    expect(asAccountState('healthy')).toBe('healthy');
    expect(asAccountState('cooling')).toBe('cooling');
    expect(asAccountState('weird')).toBe('quarantined');
  });

  it('labels + badge variants per state', () => {
    expect(accountStateLabel('healthy')).toBe('Connected');
    expect(accountStateBadgeVariant('healthy')).toBe('success');
    expect(accountStateBadgeVariant('cooling')).toBe('warning');
    expect(accountStateBadgeVariant('quarantined')).toBe('danger');
  });
});

// ─── account source provenance (TASK-130) ───────────────────────────────────────

describe('account source helpers', () => {
  it('narrows known sources, unknown/empty → manual (fail-safe default)', () => {
    expect(asAccountSource('manual')).toBe('manual');
    expect(asAccountSource('auto')).toBe('auto');
    expect(asAccountSource('weird')).toBe('manual');
    expect(asAccountSource(null)).toBe('manual');
    expect(asAccountSource(undefined)).toBe('manual');
  });

  it('labels each source for the badge', () => {
    expect(accountSourceLabel('manual')).toBe('Manual');
    expect(accountSourceLabel('auto')).toBe('Auto');
  });

  it('maps each source to an existing fs-badge variant', () => {
    expect(accountSourceBadgeVariant('manual')).toBe('neutral');
    expect(accountSourceBadgeVariant('auto')).toBe('info');
  });
});

describe('formatCooldown', () => {
  it('formats whole seconds as m:ss; null/0 → null', () => {
    expect(formatCooldown(null)).toBeNull();
    expect(formatCooldown(0)).toBeNull();
    expect(formatCooldown(42)).toBe('0:42');
    expect(formatCooldown(125)).toBe('2:05');
    expect(formatCooldown(41.2)).toBe('0:42'); // ceil
  });
});

// ─── not-found guard decision ───────────────────────────────────────────────────

describe('shouldShowPoolAdminNotFound', () => {
  it('loading (undefined) / unauthenticated (null) → false', () => {
    expect(shouldShowPoolAdminNotFound(undefined, undefined)).toBe(false);
    expect(shouldShowPoolAdminNotFound(null, undefined)).toBe(false);
  });

  it('regular user → not-found (no existence leak)', () => {
    expect(shouldShowPoolAdminNotFound({ is_superuser: false }, undefined)).toBe(true);
  });

  it('superuser → page renders; racy 403 → not-found', () => {
    expect(shouldShowPoolAdminNotFound({ is_superuser: true }, undefined)).toBe(false);
    expect(shouldShowPoolAdminNotFound({ is_superuser: true }, 403)).toBe(true);
  });
});

// ─── TASK-136: factory api ─────────────────────────────────────────────────────

describe('factory api — correct paths', () => {
  it('getFactoryAccounts GETs /factory/accounts', async () => {
    mockedGet.mockResolvedValueOnce({ data: [] });
    await getFactoryAccounts();
    expect(mockedGet).toHaveBeenCalledWith('/factory/accounts');
  });

  it('getFactoryBudget GETs /factory/budget', async () => {
    const budget = {
      budget_usd: '10.00',
      enabled: true,
      provider: 'smsactivate',
      remaining_usd: '8.00',
      spent_usd: '2.00',
    };
    mockedGet.mockResolvedValueOnce({ data: budget });
    const result = await getFactoryBudget();
    expect(mockedGet).toHaveBeenCalledWith('/factory/budget');
    expect(result).toEqual(budget);
  });

  it('triggerFactory POSTs /factory/accounts', async () => {
    mockedPost.mockResolvedValueOnce({ data: { status: 'triggered' } });
    const result = await triggerFactory();
    expect(mockedPost).toHaveBeenCalledWith('/factory/accounts');
    expect(result).toEqual({ status: 'triggered' });
  });

  it('reloginFactory(7) POSTs /factory/accounts/7/relogin', async () => {
    mockedPost.mockResolvedValueOnce({ data: { status: 'triggered' } });
    await reloginFactory(7);
    expect(mockedPost).toHaveBeenCalledWith('/factory/accounts/7/relogin');
  });
});

// ─── TASK-136: factory query options ──────────────────────────────────────────

describe('factoryAccountsQueryOptions', () => {
  it('uses the stable key, never retries, fetches only when enabled', () => {
    expect(FACTORY_ACCOUNTS_QUERY_KEY).toEqual(['admin', 'factory-accounts']);
    const enabled = factoryAccountsQueryOptions(true);
    expect(enabled.queryKey).toEqual(FACTORY_ACCOUNTS_QUERY_KEY);
    expect(enabled.retry).toBe(false);
    expect(enabled.enabled).toBe(true);
    expect(factoryAccountsQueryOptions(false).enabled).toBe(false);
  });
});

describe('factoryBudgetQueryOptions', () => {
  it('uses the stable key, never retries, fetches only when enabled', () => {
    expect(FACTORY_BUDGET_QUERY_KEY).toEqual(['admin', 'factory-budget']);
    const enabled = factoryBudgetQueryOptions(true);
    expect(enabled.queryKey).toEqual(FACTORY_BUDGET_QUERY_KEY);
    expect(enabled.retry).toBe(false);
    expect(enabled.enabled).toBe(true);
    expect(factoryBudgetQueryOptions(false).enabled).toBe(false);
  });
});

// ─── TASK-136: factory lib — state narrowing + labels + badge variants ─────────

describe('asFactoryAccountState', () => {
  it('narrows all known backend states', () => {
    expect(asFactoryAccountState('purchased')).toBe('purchased');
    expect(asFactoryAccountState('registered')).toBe('registered');
    expect(asFactoryAccountState('probation')).toBe('probation');
    expect(asFactoryAccountState('promoted')).toBe('promoted');
    expect(asFactoryAccountState('failed')).toBe('failed');
    expect(asFactoryAccountState('banned')).toBe('banned');
  });

  it('unknown state → "failed" (fail-safe)', () => {
    expect(asFactoryAccountState('bogus')).toBe('failed');
    expect(asFactoryAccountState('')).toBe('failed');
  });
});

describe('factoryStateLabel', () => {
  it('returns a human label for each state', () => {
    expect(factoryStateLabel('purchased')).toBeTypeOf('string');
    expect(factoryStateLabel('registered')).toBeTypeOf('string');
    expect(factoryStateLabel('probation')).toBeTypeOf('string');
    expect(factoryStateLabel('promoted')).toBeTypeOf('string');
    expect(factoryStateLabel('failed')).toBeTypeOf('string');
    expect(factoryStateLabel('banned')).toBeTypeOf('string');
    // Spot-check specific labels
    expect(factoryStateLabel('promoted')).toMatch(/promot/i);
    expect(factoryStateLabel('failed')).toMatch(/fail/i);
    expect(factoryStateLabel('banned')).toMatch(/ban/i);
  });
});

describe('factoryStateBadgeVariant', () => {
  it('promoted → success', () => {
    expect(factoryStateBadgeVariant('promoted')).toBe('success');
  });
  it('probation → info', () => {
    expect(factoryStateBadgeVariant('probation')).toBe('info');
  });
  it('failed + banned → danger', () => {
    expect(factoryStateBadgeVariant('failed')).toBe('danger');
    expect(factoryStateBadgeVariant('banned')).toBe('danger');
  });
  it('purchased + registered → warning', () => {
    expect(factoryStateBadgeVariant('purchased')).toBe('warning');
    expect(factoryStateBadgeVariant('registered')).toBe('warning');
  });
});

// ─── TASK-136: formatProbationCountdown ───────────────────────────────────────

describe('formatProbationCountdown', () => {
  const NOW = new Date('2026-06-20T12:00:00.000Z');

  it('null probationUntil → null', () => {
    expect(formatProbationCountdown(null, NOW)).toBeNull();
  });

  it('already elapsed → null', () => {
    expect(formatProbationCountdown('2026-06-20T11:59:59.000Z', NOW)).toBeNull();
    expect(formatProbationCountdown('2026-06-19T10:00:00.000Z', NOW)).toBeNull();
  });

  it('3d 4h in the future', () => {
    const future = new Date(NOW.getTime() + (3 * 24 * 60 + 4 * 60) * 60 * 1000);
    const result = formatProbationCountdown(future.toISOString(), NOW);
    expect(result).toBe('3d 4h');
  });

  it('less than a day shows hours and minutes', () => {
    const future = new Date(NOW.getTime() + (5 * 60 + 30) * 60 * 1000); // 5h 30m
    const result = formatProbationCountdown(future.toISOString(), NOW);
    expect(result).toBe('5h 30m');
  });

  it('less than an hour shows only minutes', () => {
    const future = new Date(NOW.getTime() + 42 * 60 * 1000); // 42m
    const result = formatProbationCountdown(future.toISOString(), NOW);
    expect(result).toBe('42m');
  });

  it('uses Date.now() when now is not injected (smoke test, no assertion on value)', () => {
    const future = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    expect(formatProbationCountdown(future)).not.toBeNull();
  });
});

// ─── TASK-136: isFactoryRegisterDisabled / factoryRegisterDisabledTooltip ─────

describe('isFactoryRegisterDisabled', () => {
  it('undefined budget → disabled (loading)', () => {
    expect(isFactoryRegisterDisabled(undefined)).toBe(true);
  });

  it('enabled:false → disabled', () => {
    const budget: FactoryBudget = {
      budget_usd: '10.00',
      enabled: false,
      provider: '',
      remaining_usd: '10.00',
      spent_usd: '0.00',
    };
    expect(isFactoryRegisterDisabled(budget)).toBe(true);
  });

  it('enabled:true → NOT disabled', () => {
    const budget: FactoryBudget = {
      budget_usd: '10.00',
      enabled: true,
      provider: 'smsactivate',
      remaining_usd: '8.00',
      spent_usd: '2.00',
    };
    expect(isFactoryRegisterDisabled(budget)).toBe(false);
  });
});

describe('factoryRegisterDisabledTooltip', () => {
  it('returns a non-empty string mentioning disabled/provider', () => {
    const tip = factoryRegisterDisabledTooltip();
    expect(tip).toBeTypeOf('string');
    expect(tip.length).toBeGreaterThan(0);
    // Should mention the factory being disabled or provider not configured
    expect(tip.toLowerCase()).toMatch(/disabled|provider|factory/);
  });
});
