/**
 * Unit tests: backend-error.ts — mapBackendError (TASK-030 AC5).
 *
 * Primary: discriminates by error.code from the unified envelope.
 * Fallback: HTTP status code when envelope absent (legacy/proxy response).
 *
 * Tests all ErrorCode values → correct kind, details parsing for VALIDATION,
 * and legacy fallback behaviour.
 */

import { describe, it, expect } from 'vitest';
import { mapBackendError } from '../../../src/shared/lib/backend-error';
import type { BackendErrorState, ValidationDetailItem } from '../../../src/shared/lib/backend-error';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build an Axios-like error with the TASK-030 unified envelope. */
function makeEnvelopeError(
  code: string,
  message: string,
  httpStatus: number,
  details?: ValidationDetailItem[],
): unknown {
  const errorBody: Record<string, unknown> = { code, message };
  if (details !== undefined) {
    errorBody.details = details;
  }
  return {
    response: {
      status: httpStatus,
      data: { error: errorBody },
    },
    message: `Request failed with status code ${httpStatus}`,
  };
}

/** Build an Axios-like error WITHOUT envelope (legacy {detail: ...} format). */
function makeLegacyError(status: number, detail?: unknown): unknown {
  return {
    response: {
      status,
      data: detail !== undefined ? { detail } : {},
    },
    message: `Request failed with status code ${status}`,
  };
}

/** Build a network error (no response). */
function makeNetworkError(): unknown {
  return { message: 'Network Error' };
}

// ---------------------------------------------------------------------------
// Primary: error.code discrimination
// ---------------------------------------------------------------------------

describe('mapBackendError — envelope error.code (primary)', () => {
  it('UNAUTHORIZED → kind=unauthorized', () => {
    const state = mapBackendError(makeEnvelopeError('UNAUTHORIZED', 'Not authenticated', 401));
    expect(state.kind).toBe('unauthorized');
    expect((state as BackendErrorState & { kind: 'unauthorized' }).message).toBeTruthy();
  });

  it('PLAN_LIMIT_EXCEEDED → kind=quota', () => {
    const state = mapBackendError(makeEnvelopeError('PLAN_LIMIT_EXCEEDED', 'Plan limit', 402));
    expect(state.kind).toBe('quota');
  });

  it('FEATURE_NOT_AVAILABLE → kind=feature-gate', () => {
    const state = mapBackendError(makeEnvelopeError('FEATURE_NOT_AVAILABLE', 'Feature locked', 403));
    expect(state.kind).toBe('feature-gate');
  });

  it('FORBIDDEN → kind=forbidden', () => {
    const state = mapBackendError(makeEnvelopeError('FORBIDDEN', 'Forbidden', 403));
    expect(state.kind).toBe('forbidden');
  });

  it('NOT_FOUND → kind=not-found', () => {
    const state = mapBackendError(makeEnvelopeError('NOT_FOUND', 'Not found', 404));
    expect(state.kind).toBe('not-found');
  });

  it('DUPLICATE → kind=duplicate', () => {
    const state = mapBackendError(makeEnvelopeError('DUPLICATE', 'Duplicate entry', 409));
    expect(state.kind).toBe('duplicate');
  });

  it('VALIDATION → kind=field with details', () => {
    const details: ValidationDetailItem[] = [
      { field: 'channel.handle', message: 'Invalid handle format' },
      { field: 'topic', message: 'Field required' },
    ];
    const state = mapBackendError(makeEnvelopeError('VALIDATION', 'Validation failed', 422, details));
    expect(state.kind).toBe('field');
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(fieldState.fields['channel.handle']).toBe('Invalid handle format');
    expect(fieldState.fields['topic']).toBe('Field required');
  });

  it('VALIDATION with empty details → kind=field with empty fields', () => {
    const state = mapBackendError(makeEnvelopeError('VALIDATION', 'Validation failed', 422, []));
    expect(state.kind).toBe('field');
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(Object.keys(fieldState.fields)).toHaveLength(0);
  });

  it('RATE_LIMITED → kind=rate-limited', () => {
    const state = mapBackendError(makeEnvelopeError('RATE_LIMITED', 'Rate limit exceeded', 429));
    expect(state.kind).toBe('rate-limited');
  });

  it('BILLING_NOT_CONFIGURED → kind=billing-not-configured', () => {
    const state = mapBackendError(makeEnvelopeError('BILLING_NOT_CONFIGURED', 'Not configured', 503));
    expect(state.kind).toBe('billing-not-configured');
  });

  it('INTERNAL → kind=generic', () => {
    const state = mapBackendError(makeEnvelopeError('INTERNAL', 'Internal error', 500));
    expect(state.kind).toBe('generic');
  });

  it('unknown code falls back to HTTP status mapping', () => {
    const state = mapBackendError(makeEnvelopeError('SOME_FUTURE_CODE', 'Something', 402));
    // Unknown code → fallback to HTTP 402 → quota
    expect(state.kind).toBe('quota');
  });

  it('envelope message is used as the primary message source', () => {
    const state = mapBackendError(makeEnvelopeError('NOT_FOUND', 'Custom not found message', 404));
    expect((state as BackendErrorState & { kind: 'not-found' }).message).toBe('Custom not found message');
  });
});

// ---------------------------------------------------------------------------
// Legacy fallback: HTTP status (no envelope)
// ---------------------------------------------------------------------------

describe('mapBackendError — legacy HTTP status fallback', () => {
  it('401 → kind=unauthorized (no envelope)', () => {
    const state = mapBackendError(makeLegacyError(401, 'Unauthorized'));
    expect(state.kind).toBe('unauthorized');
  });

  it('402 → kind=quota (legacy)', () => {
    const state = mapBackendError(makeLegacyError(402, 'Plan limit exceeded'));
    expect(state.kind).toBe('quota');
    expect((state as BackendErrorState & { kind: 'quota' }).message).toBeTruthy();
  });

  it('403 → kind=feature-gate (legacy, ambiguous 403)', () => {
    const state = mapBackendError(makeLegacyError(403, 'Feature not available'));
    // Legacy 403 → feature-gate (previous behavior preserved for fallback)
    expect(state.kind).toBe('feature-gate');
  });

  it('404 → kind=not-found (legacy)', () => {
    const state = mapBackendError(makeLegacyError(404, 'Not found'));
    expect(state.kind).toBe('not-found');
  });

  it('409 → kind=duplicate (legacy)', () => {
    const state = mapBackendError(makeLegacyError(409, 'Duplicate'));
    expect(state.kind).toBe('duplicate');
  });

  it('422 with Pydantic legacy array detail → kind=field with stripped body prefix', () => {
    const detail = [
      { loc: ['body', 'channel', 'handle'], msg: 'Invalid handle format', type: 'value_error' },
      { loc: ['body', 'topic'], msg: 'Field required', type: 'missing' },
    ];
    const state = mapBackendError(makeLegacyError(422, detail));
    // Legacy 422 with Pydantic array detail → field (statusToKind(422) = 'field')
    expect(state.kind).toBe('field');
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(fieldState.fields['channel.handle']).toBe('Invalid handle format');
    expect(fieldState.fields['topic']).toBe('Field required');
  });

  it('429 → kind=rate-limited (legacy)', () => {
    const state = mapBackendError(makeLegacyError(429, 'Rate limit'));
    expect(state.kind).toBe('rate-limited');
  });

  it('503 → kind=billing-not-configured (legacy)', () => {
    const state = mapBackendError(makeLegacyError(503, 'Service unavailable'));
    expect(state.kind).toBe('billing-not-configured');
  });

  it('500 → kind=generic (legacy)', () => {
    const state = mapBackendError(makeLegacyError(500, 'Server error'));
    expect(state.kind).toBe('generic');
  });

  it('400 → kind=generic (legacy)', () => {
    const state = mapBackendError(makeLegacyError(400, 'Bad request'));
    expect(state.kind).toBe('generic');
  });
});

// ---------------------------------------------------------------------------
// VALIDATION details: field path normalisation
// ---------------------------------------------------------------------------

describe('mapBackendError — VALIDATION field path normalisation', () => {
  it('envelope details: field path is used as-is (normalised by backend)', () => {
    const details: ValidationDetailItem[] = [
      { field: 'alert_config.score_threshold', message: 'Out of range' },
    ];
    const state = mapBackendError(makeEnvelopeError('VALIDATION', 'Validation failed', 422, details));
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(fieldState.fields['alert_config.score_threshold']).toBe('Out of range');
  });

  it('envelope details: root field (empty field string) → "root" key', () => {
    const details: ValidationDetailItem[] = [
      { field: '', message: 'Root error' },
    ];
    const state = mapBackendError(makeEnvelopeError('VALIDATION', 'Validation failed', 422, details));
    const fieldState = state as BackendErrorState & { kind: 'field' };
    expect(fieldState.fields['root']).toBe('Root error');
  });

  it('legacy Pydantic detail: body prefix stripped', () => {
    // VALIDATION envelope without `details` falls back to the legacy Pydantic
    // `detail` array — the `body` prefix must be stripped from field paths.
    const noDetailsEnvelope = {
      response: {
        status: 422,
        data: {
          error: { code: 'VALIDATION', message: 'Validation failed' },
          detail: [
            { loc: ['body', 'topic'], msg: 'Field required', type: 'missing' },
          ],
        },
      },
      message: 'Request failed with status code 422',
    };
    const state = mapBackendError(noDetailsEnvelope);
    expect(state.kind).toBe('field');
    const fieldState = state as BackendErrorState & { kind: 'field' };
    // Legacy detail should be parsed with 'body' stripped
    expect(fieldState.fields['topic']).toBe('Field required');
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe('mapBackendError — edge cases', () => {
  it('network error (no response) → kind=generic', () => {
    const state = mapBackendError(makeNetworkError());
    expect(state.kind).toBe('generic');
  });

  it('completely empty object → kind=generic', () => {
    const state = mapBackendError({});
    expect(state.kind).toBe('generic');
  });

  it('envelope message is non-empty string', () => {
    const state = mapBackendError(makeEnvelopeError('DUPLICATE', 'This channel is already in your list.', 409));
    expect((state as BackendErrorState & { kind: 'duplicate' }).message).toBe('This channel is already in your list.');
  });

  it('fallback default message when neither envelope nor detail has message', () => {
    const state = mapBackendError(makeLegacyError(404));
    expect((state as BackendErrorState & { kind: 'not-found' }).message.length).toBeGreaterThan(0);
  });
});
