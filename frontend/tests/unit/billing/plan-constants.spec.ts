/**
 * Unit tests: entities/plan constants and isPlanAtLeast (TASK-017, updated TASK-049).
 *
 * Coverage:
 * - PLAN_PRICE_USD values correct per overview §6 (TASK-049: Pro $29, Trader/Team $99)
 * - PLAN_DISPLAY_NAME: "Trader" for team tier (TASK-049 display-only rename)
 * - PLAN_HISTORY_DAYS reflects backend limits
 * - PLAN_WEBHOOK_DELIVERY feature flag
 * - PLAN_MAX_WATCHLISTS per tier (TASK-049: Free=0, Pro=100, Team=500 — synced to backend CHANNELS)
 * - isPlanAtLeast ordering
 */

import { describe, it, expect } from 'vitest';
import {
  PLAN_FREE,
  PLAN_PRO,
  PLAN_TEAM,
  PLAN_PRICE_USD,
  PLAN_HISTORY_DAYS,
  PLAN_WEBHOOK_DELIVERY,
  PLAN_MAX_WATCHLISTS,
  PLAN_TIERS,
  PLAN_DISPLAY_NAME,
  isPlanAtLeast,
} from '../../../src/entities/plan/constants';

describe('plan constants', () => {
  describe('PLAN_TIERS', () => {
    it('has exactly 3 tiers in ascending order', () => {
      expect(PLAN_TIERS).toEqual([PLAN_FREE, PLAN_PRO, PLAN_TEAM]);
    });
  });

  describe('PLAN_PRICE_USD', () => {
    it('free plan has $0 price', () => {
      expect(PLAN_PRICE_USD[PLAN_FREE]).toBe(0);
    });

    it('pro plan has $29/month price (TASK-049: overview §6 / backend plans.py)', () => {
      expect(PLAN_PRICE_USD[PLAN_PRO]).toBe(29);
    });

    it('team/Trader plan has $99/month price (TASK-049: overview §6 / backend plans.py)', () => {
      expect(PLAN_PRICE_USD[PLAN_TEAM]).toBe(99);
    });

    it('all tiers have a price defined', () => {
      for (const tier of PLAN_TIERS) {
        expect(typeof PLAN_PRICE_USD[tier]).toBe('number');
      }
    });
  });

  describe('PLAN_HISTORY_DAYS', () => {
    it('free plan has 0 days (no history)', () => {
      expect(PLAN_HISTORY_DAYS[PLAN_FREE]).toBe(0);
    });

    it('pro plan has 30 days', () => {
      expect(PLAN_HISTORY_DAYS[PLAN_PRO]).toBe(30);
    });

    it('team plan has 90 days', () => {
      expect(PLAN_HISTORY_DAYS[PLAN_TEAM]).toBe(90);
    });
  });

  describe('PLAN_WEBHOOK_DELIVERY', () => {
    it('free plan does NOT have webhook delivery', () => {
      expect(PLAN_WEBHOOK_DELIVERY[PLAN_FREE]).toBe(false);
    });

    it('pro plan has webhook delivery', () => {
      expect(PLAN_WEBHOOK_DELIVERY[PLAN_PRO]).toBe(true);
    });

    it('team plan has webhook delivery', () => {
      expect(PLAN_WEBHOOK_DELIVERY[PLAN_TEAM]).toBe(true);
    });
  });

  describe('PLAN_MAX_WATCHLISTS', () => {
    // TASK-049: synced to backend CHANNELS limits (Free=0, Pro=100, Team=500).
    // Free=0: own channels blocked; curated packs are the Free value prop.
    it('free plan has 0 own channels (TASK-049: Free = funnel)', () => {
      expect(PLAN_MAX_WATCHLISTS[PLAN_FREE]).toBe(0);
    });

    it('pro plan has 100 channels (synced to backend CHANNELS limit)', () => {
      expect(PLAN_MAX_WATCHLISTS[PLAN_PRO]).toBe(100);
    });

    it('team/Trader plan has 500 channels (synced to backend CHANNELS limit)', () => {
      expect(PLAN_MAX_WATCHLISTS[PLAN_TEAM]).toBe(500);
    });
  });

  describe('PLAN_DISPLAY_NAME', () => {
    it('free displays as "Free"', () => {
      expect(PLAN_DISPLAY_NAME[PLAN_FREE]).toBe('Free');
    });

    it('pro displays as "Pro"', () => {
      expect(PLAN_DISPLAY_NAME[PLAN_PRO]).toBe('Pro');
    });

    it('team displays as "Trader" (TASK-049: display-only rename; enum value stays "team")', () => {
      expect(PLAN_DISPLAY_NAME[PLAN_TEAM]).toBe('Trader');
    });
  });

  describe('isPlanAtLeast', () => {
    it('free is at least free', () => {
      expect(isPlanAtLeast(PLAN_FREE, PLAN_FREE)).toBe(true);
    });

    it('pro is at least free', () => {
      expect(isPlanAtLeast(PLAN_PRO, PLAN_FREE)).toBe(true);
    });

    it('pro is at least pro', () => {
      expect(isPlanAtLeast(PLAN_PRO, PLAN_PRO)).toBe(true);
    });

    it('pro is NOT at least team', () => {
      expect(isPlanAtLeast(PLAN_PRO, PLAN_TEAM)).toBe(false);
    });

    it('team is at least pro', () => {
      expect(isPlanAtLeast(PLAN_TEAM, PLAN_PRO)).toBe(true);
    });

    it('team is at least team', () => {
      expect(isPlanAtLeast(PLAN_TEAM, PLAN_TEAM)).toBe(true);
    });

    it('free is NOT at least pro', () => {
      expect(isPlanAtLeast(PLAN_FREE, PLAN_PRO)).toBe(false);
    });

    it('free is NOT at least team', () => {
      expect(isPlanAtLeast(PLAN_FREE, PLAN_TEAM)).toBe(false);
    });
  });
});
