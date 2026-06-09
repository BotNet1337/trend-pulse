/**
 * Unit tests: useAlerts infinite-query cursor pagination (TASK-020).
 *
 * Tests the getNextPageParam logic and initialPageParam without mounting React.
 * We exercise the cursor logic by calling the extracted helpers directly.
 */

import { describe, it, expect } from 'vitest';
import type { AlertListResponse } from '../../../src/entities/alert/model';
// Import the REAL helpers used by useAlerts (not a copy) so a regression in
// queries.ts (e.g. returning null instead of undefined) fails this test.
import {
  alertsNextPageParam as getNextPageParam,
  ALERTS_INITIAL_PAGE_PARAM,
} from '../../../src/features/alerts/queries';

// ─── Fixtures ────────────────────────────────────────────────────────────────

function makeAlertListResponse(
  next_cursor: string | null,
  itemCount = 2,
  idOffset = 0,
): AlertListResponse {
  return {
    items: Array.from({ length: itemCount }, (_, i) => ({
      id: idOffset + i + 1,
      score: 80 + i,
      topic: `topic-${idOffset + i}`,
      first_seen: new Date().toISOString(),
      channels_count: i + 1,
      delivery_status: 'delivered',
    })),
    next_cursor,
    history_unavailable: false,
  };
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('useAlerts cursor pagination logic', () => {
  describe('initialPageParam', () => {
    it('initial page param is null (first page, no cursor)', () => {
      // Real exported value from queries.ts — first page carries no cursor.
      expect(ALERTS_INITIAL_PAGE_PARAM).toBeNull();
    });
  });

  describe('getNextPageParam', () => {
    it('returns next_cursor string when there are more pages', () => {
      const cursor = 'eyJmcyI6IjIwMjYtMDYtMDlUMTI6MDA6MDBaIiwiaWQiOjF9';
      const page = makeAlertListResponse(cursor);
      expect(getNextPageParam(page)).toBe(cursor);
    });

    it('returns undefined (not null) when next_cursor is null — stops pagination', () => {
      const page = makeAlertListResponse(null);
      // useInfiniteQuery stops when getNextPageParam returns undefined
      expect(getNextPageParam(page)).toBeUndefined();
    });

    it('returns undefined for empty items on last page', () => {
      const page = makeAlertListResponse(null, 0);
      expect(getNextPageParam(page)).toBeUndefined();
    });

    it('returns cursor string for non-empty page with more items', () => {
      const cursor = 'abc123';
      const page = makeAlertListResponse(cursor, 20);
      expect(getNextPageParam(page)).toBe(cursor);
    });
  });

  describe('cursor pagination sequence', () => {
    it('simulates multi-page traversal stopping on null next_cursor', () => {
      const pages: AlertListResponse[] = [
        makeAlertListResponse('cursor1', 20),
        makeAlertListResponse('cursor2', 20),
        makeAlertListResponse(null, 5), // last page
      ];

      // Simulate the infinite query loop
      const cursors: Array<string | undefined> = [];
      for (const page of pages) {
        cursors.push(getNextPageParam(page));
      }

      expect(cursors[0]).toBe('cursor1');
      expect(cursors[1]).toBe('cursor2');
      expect(cursors[2]).toBeUndefined(); // stops here
    });

    it('collects all items across pages without duplication', () => {
      const page1 = makeAlertListResponse('cursor1', 3, 0);
      const page2 = makeAlertListResponse(null, 2, 3);

      const allItems = [...page1.items, ...page2.items];
      const allIds = allItems.map((i) => i.id);

      expect(allItems).toHaveLength(5);
      expect(new Set(allIds).size).toBe(5); // no duplicates
    });
  });

  describe('history_unavailable', () => {
    it('history_unavailable=true with empty items and null cursor (Free plan)', () => {
      const freePlanPage: AlertListResponse = {
        items: [],
        next_cursor: null,
        history_unavailable: true,
      };

      expect(freePlanPage.history_unavailable).toBe(true);
      expect(freePlanPage.items).toHaveLength(0);
      expect(getNextPageParam(freePlanPage)).toBeUndefined();
    });
  });
});
