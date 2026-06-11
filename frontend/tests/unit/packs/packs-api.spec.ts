/**
 * Unit tests: packs API module — type shapes and error-message extraction.
 *
 * We test the extractErrorMessage logic from error-message.ts to verify
 * the 402 → human-readable plan limit message path works correctly, without
 * mounting components (no jsdom — vitest runs in node environment here).
 */

import { describe, it, expect } from 'vitest';
import { extractErrorMessage } from '../../../src/features/packs/error-message';

describe('packs extractErrorMessage', () => {
  it('maps 402 with envelope error.message to localised quota message (TASK-030 envelope first)', () => {
    const err = {
      response: {
        status: 402,
        data: { error: { message: 'packs limit reached: the free plan allows 1' } },
      },
    };
    const msg = extractErrorMessage(err);
    expect(msg).toContain('Лимит паков');
    expect(msg).toContain('packs limit reached');
  });

  it('maps 402 with legacy {detail} to localised quota message (legacy fallback)', () => {
    const err = { response: { status: 402, data: { detail: 'packs limit reached: the free plan allows 1' } } };
    const msg = extractErrorMessage(err);
    expect(msg).toContain('Лимит паков');
    expect(msg).toContain('packs limit reached');
  });

  it('maps 402 without detail to default quota message', () => {
    const err = { response: { status: 402, data: {} } };
    const msg = extractErrorMessage(err);
    expect(msg).toBe(
      'Вы достигли лимита паков на текущем тарифе. Обновите план, чтобы добавить больше.',
    );
  });

  it('maps 404 to not-found message', () => {
    const err = { response: { status: 404, data: { detail: 'pack not found' } } };
    const msg = extractErrorMessage(err);
    expect(msg).toBe('Набор не найден.');
  });

  it('maps 500 to generic message', () => {
    const err = { response: { status: 500, data: {} } };
    const msg = extractErrorMessage(err);
    expect(msg).toBe('Что-то пошло не так. Попробуйте ещё раз.');
  });

  it('maps network error (no response) to generic message', () => {
    const msg = extractErrorMessage({ message: 'Network Error' });
    expect(msg).toBe('Что-то пошло не так. Попробуйте ещё раз.');
  });

  it('maps null to generic message', () => {
    const msg = extractErrorMessage(null);
    expect(msg).toBe('Что-то пошло не так. Попробуйте ещё раз.');
  });

  it('maps undefined to generic message', () => {
    const msg = extractErrorMessage(undefined);
    expect(msg).toBe('Что-то пошло не так. Попробуйте ещё раз.');
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
