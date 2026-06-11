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
  BILLING_PERIODS,
  PERIOD_MONTH,
  PERIOD_QUARTER,
  PERIOD_YEAR,
  PLAN_PERIOD_PRICE_USD,
  BILLING_PERIOD_LABEL,
  BILLING_PERIOD_PRICE_SUFFIX,
  BILLING_PERIOD_SAVINGS_NOTE,
  BILLING_PERIOD_BILLED_NOTE,
} from '../../../src/entities/plan/constants';
import { planCardPricing } from '../../../src/features/billing/ui/plan-card-pricing';

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

  describe('billing periods (TASK-047)', () => {
    it('exposes exactly month/quarter/year in order', () => {
      expect(BILLING_PERIODS).toEqual([PERIOD_MONTH, PERIOD_QUARTER, PERIOD_YEAR]);
    });

    it('PLAN_PERIOD_PRICE_USD matches the backend grid (Pro 29/78/278, Trader 99/267/950)', () => {
      expect(PLAN_PERIOD_PRICE_USD[PLAN_PRO]).toEqual({ month: 29, quarter: 78, year: 278 });
      expect(PLAN_PERIOD_PRICE_USD[PLAN_TEAM]).toEqual({ month: 99, quarter: 267, year: 950 });
    });

    it('free has no paid periods (always 0)', () => {
      for (const period of BILLING_PERIODS) {
        expect(PLAN_PERIOD_PRICE_USD[PLAN_FREE][period]).toBe(0);
      }
    });

    it('month column equals the PLAN_PRICE_USD monthly anchor', () => {
      for (const tier of PLAN_TIERS) {
        expect(PLAN_PERIOD_PRICE_USD[tier][PERIOD_MONTH]).toBe(PLAN_PRICE_USD[tier]);
      }
    });

    it('labels every period', () => {
      expect(BILLING_PERIOD_LABEL[PERIOD_MONTH]).toBe('Monthly');
      expect(BILLING_PERIOD_LABEL[PERIOD_QUARTER]).toBe('Quarterly');
      expect(BILLING_PERIOD_LABEL[PERIOD_YEAR]).toBe('Yearly');
    });

    it('savings note: none for month, ~10% quarter, ~20% year', () => {
      expect(BILLING_PERIOD_SAVINGS_NOTE[PERIOD_MONTH]).toBeNull();
      expect(BILLING_PERIOD_SAVINGS_NOTE[PERIOD_QUARTER]).toContain('10%');
      expect(BILLING_PERIOD_SAVINGS_NOTE[PERIOD_YEAR]).toContain('20%');
    });

    it('billed note: quarter every 3 months, year yearly', () => {
      expect(BILLING_PERIOD_BILLED_NOTE[PERIOD_MONTH]).toBeNull();
      expect(BILLING_PERIOD_BILLED_NOTE[PERIOD_QUARTER]).toBe('Billed every 3 months');
      expect(BILLING_PERIOD_BILLED_NOTE[PERIOD_YEAR]).toBe('Billed yearly');
    });
  });

  describe('planCardPricing (PlanComparison toggle, TASK-047)', () => {
    it('card amount equals the period constant for every paid plan/period', () => {
      for (const plan of [PLAN_PRO, PLAN_TEAM] as const) {
        for (const period of BILLING_PERIODS) {
          const pricing = planCardPricing(plan, period);
          expect(pricing.amountUsd).toBe(PLAN_PERIOD_PRICE_USD[plan][period]);
          expect(pricing.suffix).toBe(BILLING_PERIOD_PRICE_SUFFIX[period]);
        }
      }
    });

    it('year pricing carries the ~20% savings note and billed-yearly copy', () => {
      const pricing = planCardPricing(PLAN_PRO, PERIOD_YEAR);
      expect(pricing.amountUsd).toBe(278);
      expect(pricing.savingsNote).toContain('20%');
      expect(pricing.billedNote).toBe('Billed yearly');
    });

    it('month pricing has no savings/billed notes', () => {
      const pricing = planCardPricing(PLAN_PRO, PERIOD_MONTH);
      expect(pricing.savingsNote).toBeNull();
      expect(pricing.billedNote).toBeNull();
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
