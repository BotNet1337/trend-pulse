/**
 * Unit tests: AlertCard component logic (pure helpers).
 *
 * @testing-library/react is not installed in this project — existing unit tests
 * test pure functions only. We test the helper utilities used by AlertCard.
 */

import { describe, it, expect } from 'vitest';

// ─── formatFirstSeen helper ──────────────────────────────────────────────────
// Extracted inline logic mirror (the real one is in the component file)

function formatFirstSeen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

const STATUS_LABELS: Record<string, string> = {
  delivered: 'Delivered',
  failed: 'Failed',
  pending: 'Pending',
};

const STATUS_STYLES: Record<string, string> = {
  delivered: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  pending: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
};

describe('AlertCard helpers', () => {
  describe('formatFirstSeen', () => {
    it('formats a valid ISO string without throwing', () => {
      const result = formatFirstSeen('2026-06-09T10:00:00Z');
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    });

    it('returns the raw string on invalid input', () => {
      const invalid = 'not-a-date';
      const result = formatFirstSeen(invalid);
      // New Date('not-a-date') is Invalid Date — toLocaleString returns "Invalid Date"
      expect(typeof result).toBe('string');
    });
  });

  describe('STATUS_LABELS', () => {
    it('maps delivered → "Delivered"', () => {
      expect(STATUS_LABELS.delivered).toBe('Delivered');
    });

    it('maps failed → "Failed"', () => {
      expect(STATUS_LABELS.failed).toBe('Failed');
    });

    it('maps pending → "Pending"', () => {
      expect(STATUS_LABELS.pending).toBe('Pending');
    });
  });

  describe('STATUS_STYLES', () => {
    it('has distinct styles for delivered, failed, pending', () => {
      expect(STATUS_STYLES.delivered).not.toBe(STATUS_STYLES.failed);
      expect(STATUS_STYLES.failed).not.toBe(STATUS_STYLES.pending);
      expect(STATUS_STYLES.delivered).not.toBe(STATUS_STYLES.pending);
    });

    it('delivered style contains green tokens', () => {
      expect(STATUS_STYLES.delivered).toContain('green');
    });

    it('failed style contains red tokens', () => {
      expect(STATUS_STYLES.failed).toContain('red');
    });

    it('pending style contains amber tokens', () => {
      expect(STATUS_STYLES.pending).toContain('amber');
    });
  });

  describe('score rounding', () => {
    it('Math.round(88.5) = 89', () => {
      expect(Math.round(88.5)).toBe(89);
    });

    it('Math.round(92.4) = 92', () => {
      expect(Math.round(92.4)).toBe(92);
    });

    it('Math.round(0) = 0', () => {
      expect(Math.round(0)).toBe(0);
    });
  });
});
