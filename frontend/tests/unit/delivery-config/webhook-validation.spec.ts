/**
 * Unit tests: client-side webhook URL validation (TASK-017 AC4 UX layer).
 *
 * validateWebhookUrlClient is a UX-only guard.
 * The authoritative SSRF check lives on the backend (task-009).
 *
 * Tests:
 * - Empty/null → no error (field is optional)
 * - Non-https scheme → error
 * - Localhost/127.0.0.1 → error
 * - RFC1918 private ranges → error
 * - Valid public HTTPS → no error (null)
 */

import { describe, it, expect } from 'vitest';
import { validateWebhookUrlClient } from '../../../src/features/delivery-config/model';

describe('validateWebhookUrlClient', () => {
  // ----- Valid / no-error cases -----

  it('returns null for empty string (field not provided)', () => {
    expect(validateWebhookUrlClient('')).toBeNull();
  });

  it('returns null for a valid public HTTPS URL', () => {
    expect(validateWebhookUrlClient('https://webhook.example.com/hook')).toBeNull();
  });

  it('returns null for a valid HTTPS URL with path and query', () => {
    expect(
      validateWebhookUrlClient('https://api.example.org/v1/webhook?token=abc123'),
    ).toBeNull();
  });

  it('returns null for HTTPS with a non-standard port', () => {
    expect(validateWebhookUrlClient('https://example.com:8443/hook')).toBeNull();
  });

  // ----- Scheme errors -----

  it('rejects http:// scheme', () => {
    const err = validateWebhookUrlClient('http://example.com/hook');
    expect(err).toBeTruthy();
    expect(err).toMatch(/https/i);
  });

  it('rejects ws:// scheme', () => {
    const err = validateWebhookUrlClient('ws://example.com/hook');
    expect(err).toBeTruthy();
  });

  it('rejects bare URL with no scheme', () => {
    const err = validateWebhookUrlClient('example.com/hook');
    expect(err).toBeTruthy();
  });

  // ----- Localhost / loopback -----

  it('rejects https://localhost', () => {
    const err = validateWebhookUrlClient('https://localhost/hook');
    expect(err).toBeTruthy();
    expect(err).toMatch(/private|public|localhost/i);
  });

  it('rejects https://localhost:8080', () => {
    const err = validateWebhookUrlClient('https://localhost:8080/hook');
    expect(err).toBeTruthy();
  });

  it('rejects https://127.0.0.1', () => {
    const err = validateWebhookUrlClient('https://127.0.0.1/hook');
    expect(err).toBeTruthy();
  });

  it('rejects https://127.0.0.2 (loopback range)', () => {
    const err = validateWebhookUrlClient('https://127.0.0.2/hook');
    expect(err).toBeTruthy();
  });

  // ----- RFC1918 private ranges -----

  it('rejects 10.x.x.x range', () => {
    const err = validateWebhookUrlClient('https://10.0.0.1/hook');
    expect(err).toBeTruthy();
  });

  it('rejects 192.168.x.x range', () => {
    const err = validateWebhookUrlClient('https://192.168.1.100/hook');
    expect(err).toBeTruthy();
  });

  it('rejects 172.16.x.x range (start of /12)', () => {
    const err = validateWebhookUrlClient('https://172.16.0.1/hook');
    expect(err).toBeTruthy();
  });

  it('rejects 172.31.x.x range (end of /12)', () => {
    const err = validateWebhookUrlClient('https://172.31.255.254/hook');
    expect(err).toBeTruthy();
  });

  it('does NOT reject 172.15.x.x (just before private range)', () => {
    // 172.15.x is NOT private — should pass client-side check
    const err = validateWebhookUrlClient('https://172.15.0.1/hook');
    expect(err).toBeNull();
  });

  it('does NOT reject 172.32.x.x (just after private range)', () => {
    const err = validateWebhookUrlClient('https://172.32.0.1/hook');
    expect(err).toBeNull();
  });

  it('rejects link-local 169.254.x.x', () => {
    const err = validateWebhookUrlClient('https://169.254.0.1/hook');
    expect(err).toBeTruthy();
  });

  // ----- Invalid URL format -----

  it('returns error for clearly invalid URL format', () => {
    const err = validateWebhookUrlClient('https://not a url');
    expect(err).toBeTruthy();
  });
});
