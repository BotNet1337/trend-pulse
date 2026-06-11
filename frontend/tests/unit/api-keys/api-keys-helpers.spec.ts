/**
 * Unit tests: api-keys pure helpers (TASK-065) — error-message mapping and
 * name validation (mirrors ApiKeyCreate minLength/maxLength from openapi.json).
 *
 * EN-only product (TASK-072): assert English strings, no Cyrillic in any branch.
 */

import { describe, it, expect } from 'vitest';
import { extractApiKeysErrorMessage } from '../../../src/features/api-keys/error-message';
import {
  API_KEY_NAME_MAX_LEN,
  API_KEY_NAME_MIN_LEN,
  isApiKeyRevoked,
  validateApiKeyName,
} from '../../../src/features/api-keys/lib';

const GENERIC_MESSAGE = 'Something went wrong. Please try again.';

describe('extractApiKeysErrorMessage', () => {
  it('maps 403 (PLAN_LIMIT_EXCEEDED gate) to Trader upgrade message', () => {
    const err = {
      response: {
        status: 403,
        data: { error: { code: 'PLAN_LIMIT_EXCEEDED', message: 'api access requires team' } },
      },
    };
    const msg = extractApiKeysErrorMessage(err);
    expect(msg).toBe('API access is available on the Trader plan. Upgrade to create API keys.');
  });

  it('maps 403 without envelope to the same Trader message (no leak of raw detail)', () => {
    const msg = extractApiKeysErrorMessage({ response: { status: 403, data: {} } });
    expect(msg).toBe('API access is available on the Trader plan. Upgrade to create API keys.');
  });

  it('maps 404 to key-not-found message', () => {
    const msg = extractApiKeysErrorMessage({
      response: { status: 404, data: { error: { message: 'api key not found' } } },
    });
    expect(msg).toBe('API key not found. It may have been revoked in another session.');
  });

  it('maps 422 with envelope message to that message (validation detail)', () => {
    const msg = extractApiKeysErrorMessage({
      response: { status: 422, data: { error: { message: 'name too long' } } },
    });
    expect(msg).toBe('name too long');
  });

  it('maps 422 without detail to name-validation fallback', () => {
    const msg = extractApiKeysErrorMessage({ response: { status: 422, data: {} } });
    expect(msg).toBe('Please enter a valid key name.');
  });

  it('maps 500 / network / null / undefined to generic message', () => {
    expect(extractApiKeysErrorMessage({ response: { status: 500, data: {} } })).toBe(GENERIC_MESSAGE);
    expect(extractApiKeysErrorMessage({ message: 'Network Error' })).toBe(GENERIC_MESSAGE);
    expect(extractApiKeysErrorMessage(null)).toBe(GENERIC_MESSAGE);
    expect(extractApiKeysErrorMessage(undefined)).toBe(GENERIC_MESSAGE);
  });

  it('contains no Cyrillic in any branch (EN-only, TASK-072)', () => {
    const samples = [
      extractApiKeysErrorMessage({ response: { status: 403, data: {} } }),
      extractApiKeysErrorMessage({ response: { status: 404, data: {} } }),
      extractApiKeysErrorMessage({ response: { status: 422, data: {} } }),
      extractApiKeysErrorMessage(null),
    ];
    for (const msg of samples) {
      expect(msg).not.toMatch(/[А-Яа-яЁё]/);
    }
  });
});

describe('validateApiKeyName', () => {
  it('mirrors OpenAPI bounds: min 1, max 255', () => {
    expect(API_KEY_NAME_MIN_LEN).toBe(1);
    expect(API_KEY_NAME_MAX_LEN).toBe(255);
  });

  it('rejects empty and whitespace-only names', () => {
    expect(validateApiKeyName('')).toBe('Key name is required.');
    expect(validateApiKeyName('   ')).toBe('Key name is required.');
  });

  it('accepts a 1-char and a 255-char name', () => {
    expect(validateApiKeyName('a')).toBeNull();
    expect(validateApiKeyName('a'.repeat(255))).toBeNull();
  });

  it('rejects a 256-char name with a length message', () => {
    const msg = validateApiKeyName('a'.repeat(256));
    expect(msg).toBe('Key name must be 255 characters or fewer.');
  });

  it('error messages contain no Cyrillic (EN-only, TASK-072)', () => {
    for (const msg of [validateApiKeyName(''), validateApiKeyName('a'.repeat(256))]) {
      expect(msg).not.toMatch(/[А-Яа-яЁё]/);
    }
  });
});

describe('isApiKeyRevoked', () => {
  it('true when revoked_at is set, false when null', () => {
    expect(isApiKeyRevoked({ revoked_at: '2026-06-11T00:00:00Z' })).toBe(true);
    expect(isApiKeyRevoked({ revoked_at: null })).toBe(false);
  });
});
