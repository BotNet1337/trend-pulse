/**
 * Unit tests: handle format pre-validation.
 * Tests validateHandleFormat for correct Telegram handle patterns.
 */

import { describe, it, expect } from 'vitest';
import {
  validateHandleFormat,
  HANDLE_REGEX,
  HANDLE_FORMAT_HINT,
} from '../../../src/shared/lib/handle-format';

describe('HANDLE_REGEX', () => {
  it('matches valid handles with @prefix', () => {
    expect(HANDLE_REGEX.test('@mychannel')).toBe(true);
    expect(HANDLE_REGEX.test('@ALLCAPS12345')).toBe(true);
    expect(HANDLE_REGEX.test('@with_underscore')).toBe(true);
    expect(HANDLE_REGEX.test('@exactly5ch')).toBe(true); // 5 chars after @
  });

  it('rejects handles without @', () => {
    expect(HANDLE_REGEX.test('mychannel')).toBe(false);
    expect(HANDLE_REGEX.test('channel123')).toBe(false);
  });

  it('rejects handles shorter than 5 chars after @', () => {
    expect(HANDLE_REGEX.test('@abc')).toBe(false); // 3 chars
    expect(HANDLE_REGEX.test('@ab')).toBe(false);
    expect(HANDLE_REGEX.test('@1234')).toBe(false); // 4 chars
  });

  it('rejects handles longer than 32 chars after @', () => {
    const longHandle = '@' + 'a'.repeat(33);
    expect(HANDLE_REGEX.test(longHandle)).toBe(false);
  });

  it('rejects handles with spaces', () => {
    expect(HANDLE_REGEX.test('@my channel')).toBe(false);
    expect(HANDLE_REGEX.test('@my-channel')).toBe(false);
  });

  it('rejects handles with special chars', () => {
    expect(HANDLE_REGEX.test('@chan!')).toBe(false);
    expect(HANDLE_REGEX.test('@ch@n')).toBe(false);
  });

  it('accepts exactly 32 chars after @', () => {
    const maxHandle = '@' + 'a'.repeat(32);
    expect(HANDLE_REGEX.test(maxHandle)).toBe(true);
  });

  it('accepts exactly 5 chars after @', () => {
    const minHandle = '@' + 'a'.repeat(5);
    expect(HANDLE_REGEX.test(minHandle)).toBe(true);
  });
});

describe('validateHandleFormat', () => {
  it('returns null for valid handle', () => {
    expect(validateHandleFormat('@validhandle')).toBeNull();
  });

  it('returns error for empty string', () => {
    expect(validateHandleFormat('')).toBeTruthy();
  });

  it('returns HANDLE_FORMAT_HINT for invalid format', () => {
    expect(validateHandleFormat('notahandle')).toBe(HANDLE_FORMAT_HINT);
  });

  it('returns HANDLE_FORMAT_HINT for handle without @', () => {
    expect(validateHandleFormat('channel123')).toBe(HANDLE_FORMAT_HINT);
  });

  it('returns error for too-short handle', () => {
    expect(validateHandleFormat('@abc')).toBeTruthy();
  });
});

describe('HANDLE_FORMAT_HINT', () => {
  it('is a non-empty string', () => {
    expect(typeof HANDLE_FORMAT_HINT).toBe('string');
    expect(HANDLE_FORMAT_HINT.length).toBeGreaterThan(0);
  });
});
