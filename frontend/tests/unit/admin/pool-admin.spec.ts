/**
 * Unit tests: TG pool admin UI (TASK-117) — pure view-model helpers, API paths,
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
 */

import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../src/shared/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import { apiClient } from '../../../src/shared/api/client';
import {
  getPoolHealth,
  pollQrLogin,
  startQrLogin,
} from '../../../src/features/pool-admin/api';
import {
  POOL_HEALTH_QUERY_KEY,
  poolHealthQueryOptions,
  qrLoginPollQueryKey,
  qrLoginPollQueryOptions,
} from '../../../src/features/pool-admin/queries';
import {
  asAccountSource,
  asAccountState,
  asQrLoginStatus,
  accountSourceBadgeVariant,
  accountSourceLabel,
  accountStateBadgeVariant,
  accountStateLabel,
  formatCooldown,
  isTerminalQrStatus,
  qrStatusMessage,
  shouldShowPoolAdminNotFound,
} from '../../../src/features/pool-admin/lib';

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
