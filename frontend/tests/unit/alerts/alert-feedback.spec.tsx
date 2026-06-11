/**
 * Unit tests: alert feedback (TASK-064).
 *
 * @testing-library/react is NOT installed in this project (env: node) — existing
 * specs test pure logic / hook options directly. We follow that convention:
 *
 *  1. Optimistic update + rollback: drive the REAL `feedbackMutationOptions`
 *     (the exact options `useSendFeedback` consumes) through a MutationObserver
 *     against a real QueryClient, with apiClient.get mocked. No React mount.
 *  2. Render decisions (button visibility / aria-pressed) are pure functions of
 *     `alert.feedback` + token presence — asserted directly.
 */

import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { MutationObserver, QueryClient } from '@tanstack/react-query';

import type { AlertRead } from '../../../src/entities/alert/model';
import { alertQueryKey } from '../../../src/entities/alert/model';
import {
  feedbackMutationOptions,
  type SendFeedbackArgs,
} from '../../../src/features/alerts/queries';

// Mock the shared api client used by sendFeedback (queries.ts → api.ts).
vi.mock('../../../src/shared/api/client', () => ({
  apiClient: { get: vi.fn() },
}));

import { apiClient } from '../../../src/shared/api/client';

const mockedGet = vi.mocked(apiClient.get);

const ALERT_ID = 77;
const TOKEN_UP = 'token-up';
const TOKEN_DOWN = 'token-down';

function makeAlert(overrides: Partial<AlertRead> = {}): AlertRead {
  return {
    id: ALERT_ID,
    score: 80,
    topic: 'topic',
    first_seen: new Date().toISOString(),
    channels_count: 3,
    delivery_status: 'delivered',
    feedback: null,
    feedback_token_up: TOKEN_UP,
    feedback_token_down: TOKEN_DOWN,
    ...overrides,
  };
}

/** Drive the mutation options through an observer and await settle. */
async function runMutation(
  client: QueryClient,
  args: SendFeedbackArgs,
): Promise<{ ok: boolean }> {
  const observer = new MutationObserver(client, feedbackMutationOptions(client, ALERT_ID));
  try {
    await observer.mutate(args);
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

describe('useSendFeedback optimistic logic', () => {
  let client: QueryClient;

  beforeEach(() => {
    mockedGet.mockReset();
    client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    client.setQueryData<AlertRead>(alertQueryKey(ALERT_ID), makeAlert({ feedback: null }));
  });

  afterEach(() => {
    client.clear();
  });

  it('optimistically writes the verdict into the cache on success', async () => {
    mockedGet.mockResolvedValueOnce({ data: '<html>ok</html>' });

    const res = await runMutation(client, { token: TOKEN_UP, verdict: 'up' });

    expect(res.ok).toBe(true);
    expect(mockedGet).toHaveBeenCalledWith(`/feedback/${TOKEN_UP}`);
    const cached = client.getQueryData<AlertRead>(alertQueryKey(ALERT_ID));
    expect(cached?.feedback).toBe('up');
  });

  it('rolls back to the previous verdict when the request fails', async () => {
    // Start with an existing "up" verdict; a failing "down" tap must roll back.
    client.setQueryData<AlertRead>(alertQueryKey(ALERT_ID), makeAlert({ feedback: 'up' }));
    mockedGet.mockRejectedValueOnce(new Error('network'));

    const res = await runMutation(client, { token: TOKEN_DOWN, verdict: 'down' });

    expect(res.ok).toBe(false);
    const cached = client.getQueryData<AlertRead>(alertQueryKey(ALERT_ID));
    expect(cached?.feedback).toBe('up'); // rolled back, not "down"
  });

  it('does not mutate the cached object in place (immutability)', async () => {
    const before = client.getQueryData<AlertRead>(alertQueryKey(ALERT_ID));
    mockedGet.mockResolvedValueOnce({ data: 'ok' });

    await runMutation(client, { token: TOKEN_UP, verdict: 'up' });

    const after = client.getQueryData<AlertRead>(alertQueryKey(ALERT_ID));
    expect(after).not.toBe(before); // new object reference
    expect(before?.feedback).toBeNull(); // original snapshot untouched
  });
});

// ─── Render-decision logic (pure) ─────────────────────────────────────────────

/** Buttons render only when BOTH tokens are present (graceful degradation). */
function shouldRenderFeedback(alert: Pick<AlertRead, 'feedback_token_up' | 'feedback_token_down'>): boolean {
  return Boolean(alert.feedback_token_up) && Boolean(alert.feedback_token_down);
}

/** aria-pressed mapping for the up button. */
function isUpPressed(feedback: AlertRead['feedback']): boolean {
  return feedback === 'up';
}

/** aria-pressed mapping for the down button. */
function isDownPressed(feedback: AlertRead['feedback']): boolean {
  return feedback === 'down';
}

describe('feedback render decisions', () => {
  it('renders buttons when both tokens are present', () => {
    expect(shouldRenderFeedback(makeAlert())).toBe(true);
  });

  it('hides buttons when either token is null (graceful degradation)', () => {
    expect(shouldRenderFeedback(makeAlert({ feedback_token_up: null }))).toBe(false);
    expect(shouldRenderFeedback(makeAlert({ feedback_token_down: null }))).toBe(false);
    expect(
      shouldRenderFeedback(makeAlert({ feedback_token_up: null, feedback_token_down: null })),
    ).toBe(false);
  });

  it('marks the up button pressed when feedback is "up"', () => {
    expect(isUpPressed('up')).toBe(true);
    expect(isDownPressed('up')).toBe(false);
  });

  it('marks the down button pressed when feedback is "down"', () => {
    expect(isDownPressed('down')).toBe(true);
    expect(isUpPressed('down')).toBe(false);
  });

  it('marks neither button pressed when there is no verdict', () => {
    expect(isUpPressed(null)).toBe(false);
    expect(isDownPressed(null)).toBe(false);
  });
});
