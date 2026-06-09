/**
 * Unit tests: backend error mapping — mapBackendError.
 * Tests all HTTP status mappings: 402/403/422/404/409/other.
 */

import { describe, it, expect } from 'vitest';
import { mapBackendError } from '../../../src/shared/lib/backend-error';
import type { BackendErrorState } from '../../../src/shared/lib/backend-error';

function makeError(status: number, detail?: unknown): unknown {
  return {
    response: {
      status,
      data: { detail },
    },
    message: `Request failed with status code ${status}`,
  };
}

describe('mapBackendError', () => {
  it('maps 402 to quota state', () => {
    const state = mapBackendError(makeError(402, 'Plan limit exceeded'));
    expect(state.kind).toBe('quota');
    expect((state as BackendErrorState & { kind: 'quota' }).message).toBeTruthy();
  });

  it('maps 402 with no detail to default quota message', () => {
    const state = mapBackendError(makeError(402));
    expect(state.kind).toBe('quota');
    expect((state as BackendErrorState & { kind: 'quota' }).message.length).toBeGreaterThan(0);
  });

  it('maps 403 to feature-gate state', () => {
    const state = mapBackendError(makeError(403, 'Feature not available'));
    expect(state.kind).toBe('feature-gate');
    expect((state as BackendErrorState & { kind: 'feature-gate' }).message).toBeTruthy();
  });

  it('maps 422 with array detail to field state', () => {
    const detail = [
      { loc: ['body', 'channel', 'handle'], msg: 'Invalid handle format', type: 'value_error' },
      { loc: ['body', 'topic'], msg: 'Field required', type: 'missing' },
    ];
    const state = mapBackendError(makeError(422, detail));
    expect(state.kind).toBe('field');
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(fieldState.fields['channel.handle']).toBe('Invalid handle format');
    expect(fieldState.fields['topic']).toBe('Field required');
  });

  it('maps 422 with empty detail array to field state with empty fields', () => {
    const state = mapBackendError(makeError(422, []));
    expect(state.kind).toBe('field');
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(Object.keys(fieldState.fields)).toHaveLength(0);
  });

  it('maps 422 with string detail to field state with message', () => {
    const state = mapBackendError(makeError(422, 'Invalid input'));
    expect(state.kind).toBe('field');
  });

  it('maps 404 to not-found state', () => {
    const state = mapBackendError(makeError(404, 'Not found'));
    expect(state.kind).toBe('not-found');
    expect((state as BackendErrorState & { kind: 'not-found' }).message).toBeTruthy();
  });

  it('maps 409 to duplicate state', () => {
    const state = mapBackendError(makeError(409, 'Duplicate'));
    expect(state.kind).toBe('duplicate');
    expect((state as BackendErrorState & { kind: 'duplicate' }).message).toBeTruthy();
  });

  it('maps unknown status to generic state', () => {
    const state = mapBackendError(makeError(500, 'Server error'));
    expect(state.kind).toBe('generic');
  });

  it('maps 400 to generic state', () => {
    const state = mapBackendError(makeError(400, 'Bad request'));
    expect(state.kind).toBe('generic');
  });

  it('handles error with no response (network error) as generic', () => {
    const state = mapBackendError({ message: 'Network Error' });
    expect(state.kind).toBe('generic');
  });

  it('422: strips "body" from loc path', () => {
    const detail = [
      { loc: ['body', 'alert_config', 'score_threshold'], msg: 'Out of range', type: 'value_error' },
    ];
    const state = mapBackendError(makeError(422, detail));
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(fieldState.fields['alert_config.score_threshold']).toBe('Out of range');
  });
});
