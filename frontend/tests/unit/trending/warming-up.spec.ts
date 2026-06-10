/**
 * Unit tests: warming_up semantics for TrendingList render decision (TASK-039).
 *
 * Tests the pure "which render state to show" logic:
 *   - warming_up=true → show warming_up placeholder
 *   - warming_up=false + items=[] → show honest empty state
 *   - warming_up=false + items present → show list
 *
 * Pattern: pure logic, no React mount.
 */

import { describe, it, expect } from 'vitest';

type RenderState = 'loading' | 'error' | 'warming_up' | 'empty' | 'list';

/**
 * resolveTrendingRenderState — pure helper mirroring TrendingList render logic.
 */
function resolveTrendingRenderState(opts: {
  isLoading: boolean;
  isError: boolean;
  warmingUp: boolean;
  itemCount: number;
}): RenderState {
  const { isLoading, isError, warmingUp, itemCount } = opts;
  if (isLoading) return 'loading';
  if (isError) return 'error';
  if (warmingUp) return 'warming_up';
  if (itemCount === 0) return 'empty';
  return 'list';
}

describe('TrendingList render state', () => {
  it('is "loading" when query is still loading', () => {
    expect(
      resolveTrendingRenderState({ isLoading: true, isError: false, warmingUp: false, itemCount: 0 }),
    ).toBe('loading');
  });

  it('is "error" when query errored', () => {
    expect(
      resolveTrendingRenderState({ isLoading: false, isError: true, warmingUp: false, itemCount: 0 }),
    ).toBe('error');
  });

  it('is "warming_up" when showcase is not yet warmed (warming_up=true)', () => {
    expect(
      resolveTrendingRenderState({ isLoading: false, isError: false, warmingUp: true, itemCount: 0 }),
    ).toBe('warming_up');
  });

  it('is "empty" when showcase warmed but no items for this pack/window', () => {
    expect(
      resolveTrendingRenderState({ isLoading: false, isError: false, warmingUp: false, itemCount: 0 }),
    ).toBe('empty');
  });

  it('is "list" when items are present', () => {
    expect(
      resolveTrendingRenderState({ isLoading: false, isError: false, warmingUp: false, itemCount: 3 }),
    ).toBe('list');
  });
});
