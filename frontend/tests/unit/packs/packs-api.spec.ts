/**
 * Unit tests: packs API module — type shapes and error-message extraction.
 *
 * We test the extractErrorMessage logic from error-message.ts to verify
 * the 402 → human-readable plan limit message path works correctly, without
 * mounting components (no jsdom — vitest runs in node environment here).
 *
 * TASK-072: продукт EN-only — ассерты на английские строки; generic-ветка
 * дословно совпадает с GENERIC_ERROR_MESSAGE (shared/api/client.ts).
 */

import { describe, it, expect } from 'vitest';
import { extractErrorMessage } from '../../../src/features/packs/error-message';

const GENERIC_MESSAGE = 'Something went wrong. Please try again.';

describe('packs extractErrorMessage', () => {
  it('maps 402 with envelope error.message to quota message (TASK-030 envelope first)', () => {
    const err = {
      response: {
        status: 402,
        data: { error: { message: 'packs limit reached: the free plan allows 1' } },
      },
    };
    const msg = extractErrorMessage(err);
    expect(msg).toContain('Pack limit reached');
    expect(msg).toContain('packs limit reached');
  });

  it('maps 402 with legacy {detail} to quota message (legacy fallback)', () => {
    const err = { response: { status: 402, data: { detail: 'packs limit reached: the free plan allows 1' } } };
    const msg = extractErrorMessage(err);
    expect(msg).toContain('Pack limit reached');
    expect(msg).toContain('packs limit reached');
  });

  it('prefers envelope error.message over legacy detail when both present', () => {
    const err = {
      response: {
        status: 402,
        data: {
          error: { message: 'envelope wins' },
          detail: 'legacy loses',
        },
      },
    };
    const msg = extractErrorMessage(err);
    expect(msg).toBe('Pack limit reached: envelope wins');
    expect(msg).not.toContain('legacy loses');
  });

  it('maps 402 without detail to default quota message', () => {
    const err = { response: { status: 402, data: {} } };
    const msg = extractErrorMessage(err);
    expect(msg).toBe(
      'You have reached the pack limit on your current plan. Upgrade your plan to add more.',
    );
  });

  it('maps 404 to not-found message', () => {
    const err = { response: { status: 404, data: { detail: 'pack not found' } } };
    const msg = extractErrorMessage(err);
    expect(msg).toBe('Pack not found.');
  });

  it('maps 500 to generic message', () => {
    const err = { response: { status: 500, data: {} } };
    const msg = extractErrorMessage(err);
    expect(msg).toBe(GENERIC_MESSAGE);
  });

  it('maps network error (no response) to generic message', () => {
    const msg = extractErrorMessage({ message: 'Network Error' });
    expect(msg).toBe(GENERIC_MESSAGE);
  });

  it('maps null to generic message', () => {
    const msg = extractErrorMessage(null);
    expect(msg).toBe(GENERIC_MESSAGE);
  });

  it('maps undefined to generic message', () => {
    const msg = extractErrorMessage(undefined);
    expect(msg).toBe(GENERIC_MESSAGE);
  });

  it('contains no Cyrillic in any branch (EN-only product, TASK-072 AC1)', () => {
    const samples = [
      extractErrorMessage({ response: { status: 402, data: { detail: 'x' } } }),
      extractErrorMessage({ response: { status: 402, data: {} } }),
      extractErrorMessage({ response: { status: 404, data: {} } }),
      extractErrorMessage(null),
    ];
    for (const msg of samples) {
      expect(msg).not.toMatch(/[А-Яа-яЁё]/);
    }
  });
});

describe('packs query key', () => {
  it('PACKS_QUERY_KEY is a stable tuple', async () => {
    // Dynamic import to avoid importing React hooks in node env;
    // we only need the exported constant.
    const mod = await import('../../../src/features/packs/queries');
    expect(mod.PACKS_QUERY_KEY).toEqual(['packs', 'catalog']);
  });
});
