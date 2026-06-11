/**
 * Unit tests: admin money dashboard (TASK-063) — pure view-model helpers,
 * API path, and query options.
 *
 * @testing-library/react is NOT installed (vitest env: node) — following the
 * project convention (alert-feedback.spec.tsx, packs-api.spec.ts) we test
 * pure logic directly, no React mount:
 *  - money/percent formatting (Decimal arrives as a JSON string; NaN → '—')
 *  - retention: null ≠ 0% invariant («no matured users yet» vs '0.0%')
 *  - plan cards: empty dict → zero state, deterministic plan ordering
 *  - not-found guard decision: non-superuser OR API 403 → not-found
 *  - query: stable key ['admin','business-metrics'], retry:false (403 terminal),
 *    enabled only for superuser (request must not fire for regular users)
 */

import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../src/shared/api/client', () => ({
  apiClient: { get: vi.fn() },
}));

import { apiClient } from '../../../src/shared/api/client';
import { getBusinessMetrics } from '../../../src/features/admin-metrics/api';
import {
  ADMIN_METRICS_QUERY_KEY,
  businessMetricsQueryOptions,
} from '../../../src/features/admin-metrics/queries';
import {
  NO_RETENTION_DATA_LABEL,
  formatUsd,
  formatPercent,
  formatRetention,
  planEntries,
  totalActiveSubscriptions,
  shouldShowAdminNotFound,
} from '../../../src/features/admin-metrics/lib';

const mockedGet = vi.mocked(apiClient.get);

// ─── api ──────────────────────────────────────────────────────────────────────

describe('getBusinessMetrics', () => {
  it('GETs /ops/business-metrics and returns the payload', async () => {
    const payload = {
      mrr: '120.00',
      active_subscriptions_by_plan: { pro: 2 },
      avg_check_30d: '60.00',
      funnel_last_30d: { daily: [], conversion_free_to_paid: 0 },
      repeat_payment_rate: null,
    };
    mockedGet.mockResolvedValueOnce({ data: payload });

    const result = await getBusinessMetrics();

    expect(mockedGet).toHaveBeenCalledWith('/ops/business-metrics');
    expect(result).toEqual(payload);
  });
});

// ─── queries ──────────────────────────────────────────────────────────────────

describe('businessMetricsQueryOptions', () => {
  it('uses the stable admin query key', () => {
    expect(ADMIN_METRICS_QUERY_KEY).toEqual(['admin', 'business-metrics']);
    expect(businessMetricsQueryOptions(true).queryKey).toEqual(ADMIN_METRICS_QUERY_KEY);
  });

  it('never retries (403 is terminal) and fetches only when enabled', () => {
    const enabled = businessMetricsQueryOptions(true);
    const disabled = businessMetricsQueryOptions(false);

    expect(enabled.retry).toBe(false);
    expect(enabled.enabled).toBe(true);
    expect(disabled.enabled).toBe(false);
  });
});

// ─── formatting ───────────────────────────────────────────────────────────────

describe('formatUsd', () => {
  it('formats a Decimal-as-string to $X.XX', () => {
    expect(formatUsd('120')).toBe('$120.00');
    expect(formatUsd('59.9')).toBe('$59.90');
    expect(formatUsd('0')).toBe('$0.00');
  });

  it('renders an em dash for non-numeric input', () => {
    expect(formatUsd('not-a-number')).toBe('—');
    expect(formatUsd('')).toBe('—');
  });
});

describe('formatPercent', () => {
  it('formats a 0..1 fraction as a percentage with one decimal', () => {
    expect(formatPercent(0.125)).toBe('12.5%');
    expect(formatPercent(0)).toBe('0.0%');
    expect(formatPercent(1)).toBe('100.0%');
  });
});

describe('formatRetention (null ≠ 0% invariant)', () => {
  it('null → no-data label, never 0%', () => {
    expect(formatRetention(null)).toBe(NO_RETENTION_DATA_LABEL);
    expect(formatRetention(null)).not.toContain('%');
  });

  it('0 → literal 0.0% (real measured zero)', () => {
    expect(formatRetention(0)).toBe('0.0%');
  });

  it('fraction → percentage', () => {
    expect(formatRetention(0.42)).toBe('42.0%');
  });
});

// ─── plan cards ───────────────────────────────────────────────────────────────

describe('planEntries / totalActiveSubscriptions', () => {
  it('empty dict → no entries, zero total ("0 active" card state)', () => {
    expect(planEntries({})).toEqual([]);
    expect(totalActiveSubscriptions({})).toBe(0);
  });

  it('sorts plans alphabetically for deterministic rendering', () => {
    expect(planEntries({ team: 1, pro: 2 })).toEqual([
      ['pro', 2],
      ['team', 1],
    ]);
    expect(totalActiveSubscriptions({ team: 1, pro: 2 })).toBe(3);
  });
});

// ─── not-found guard decision ─────────────────────────────────────────────────

describe('shouldShowAdminNotFound', () => {
  it('loading user (undefined) → not yet decided (false)', () => {
    expect(shouldShowAdminNotFound(undefined, undefined)).toBe(false);
  });

  it('unauthenticated (null) → false: AuthGuard owns the redirect', () => {
    expect(shouldShowAdminNotFound(null, undefined)).toBe(false);
  });

  it('regular user → not-found (no existence leak)', () => {
    expect(shouldShowAdminNotFound({ is_superuser: false }, undefined)).toBe(true);
  });

  it('superuser with fresh flag → page renders', () => {
    expect(shouldShowAdminNotFound({ is_superuser: true }, undefined)).toBe(false);
  });

  it('stale superuser flag + API 403 → not-found (race: rights revoked)', () => {
    expect(shouldShowAdminNotFound({ is_superuser: true }, 403)).toBe(true);
  });

  it('transient 500 from API → NOT a not-found (error state instead)', () => {
    expect(shouldShowAdminNotFound({ is_superuser: true }, 500)).toBe(false);
  });
});
