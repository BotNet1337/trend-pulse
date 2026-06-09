/**
 * Unit tests: alert entity model — query keys, type structure.
 */

import { describe, it, expect } from 'vitest';
import { ALERTS_QUERY_KEY, alertQueryKey } from '../../../src/entities/alert/model';

describe('alert model', () => {
  describe('ALERTS_QUERY_KEY', () => {
    it('is a stable tuple', () => {
      expect(ALERTS_QUERY_KEY).toEqual(['alerts', 'list']);
    });
  });

  describe('alertQueryKey', () => {
    it('builds detail key with id', () => {
      expect(alertQueryKey(42)).toEqual(['alerts', 'detail', 42]);
    });

    it('uses the provided id in the key', () => {
      const key = alertQueryKey(99);
      expect(key[2]).toBe(99);
    });
  });
});
