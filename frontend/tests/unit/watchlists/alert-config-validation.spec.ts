/**
 * Unit tests: alert config client-side validation.
 * Tests validateAlertConfig for all field ranges and edge cases.
 */

import { describe, it, expect } from 'vitest';
import { validateAlertConfig } from '../../../src/features/watchlists/alert-config-validation';
import type { AlertConfig } from '../../../src/entities/watchlist/model';

const validConfig: AlertConfig = {
  score_threshold: 70,
  min_channels: 1,
  notification_lang: 'en',
};

describe('validateAlertConfig', () => {
  it('returns empty errors for valid config', () => {
    const errors = validateAlertConfig(validConfig);
    expect(Object.keys(errors)).toHaveLength(0);
  });

  describe('score_threshold', () => {
    it('allows 0', () => {
      const errors = validateAlertConfig({ ...validConfig, score_threshold: 0 });
      expect(errors.score_threshold).toBeUndefined();
    });

    it('allows 100', () => {
      const errors = validateAlertConfig({ ...validConfig, score_threshold: 100 });
      expect(errors.score_threshold).toBeUndefined();
    });

    it('allows 50.5 (float within range)', () => {
      const errors = validateAlertConfig({ ...validConfig, score_threshold: 50.5 });
      expect(errors.score_threshold).toBeUndefined();
    });

    it('rejects -1 (below 0)', () => {
      const errors = validateAlertConfig({ ...validConfig, score_threshold: -1 });
      expect(errors.score_threshold).toBeTruthy();
    });

    it('rejects 101 (above 100)', () => {
      const errors = validateAlertConfig({ ...validConfig, score_threshold: 101 });
      expect(errors.score_threshold).toBeTruthy();
    });

    it('rejects NaN', () => {
      const errors = validateAlertConfig({ ...validConfig, score_threshold: NaN });
      expect(errors.score_threshold).toBeTruthy();
    });
  });

  describe('min_channels', () => {
    it('allows 1 (minimum)', () => {
      const errors = validateAlertConfig({ ...validConfig, min_channels: 1 });
      expect(errors.min_channels).toBeUndefined();
    });

    it('allows large integers', () => {
      const errors = validateAlertConfig({ ...validConfig, min_channels: 100 });
      expect(errors.min_channels).toBeUndefined();
    });

    it('rejects 0 (below minimum)', () => {
      const errors = validateAlertConfig({ ...validConfig, min_channels: 0 });
      expect(errors.min_channels).toBeTruthy();
    });

    it('rejects -1', () => {
      const errors = validateAlertConfig({ ...validConfig, min_channels: -1 });
      expect(errors.min_channels).toBeTruthy();
    });

    it('rejects 1.5 (non-integer)', () => {
      const errors = validateAlertConfig({ ...validConfig, min_channels: 1.5 });
      expect(errors.min_channels).toBeTruthy();
    });

    it('rejects NaN', () => {
      const errors = validateAlertConfig({ ...validConfig, min_channels: NaN });
      expect(errors.min_channels).toBeTruthy();
    });
  });

  describe('notification_lang', () => {
    it('allows "en"', () => {
      const errors = validateAlertConfig({ ...validConfig, notification_lang: 'en' });
      expect(errors.notification_lang).toBeUndefined();
    });

    it('allows "ru"', () => {
      const errors = validateAlertConfig({ ...validConfig, notification_lang: 'ru' });
      expect(errors.notification_lang).toBeUndefined();
    });

    it('rejects empty string', () => {
      const errors = validateAlertConfig({ ...validConfig, notification_lang: '' });
      expect(errors.notification_lang).toBeTruthy();
    });

    it('rejects whitespace-only', () => {
      const errors = validateAlertConfig({ ...validConfig, notification_lang: '   ' });
      expect(errors.notification_lang).toBeTruthy();
    });
  });

  it('reports multiple errors simultaneously', () => {
    const errors = validateAlertConfig({
      score_threshold: -5,
      min_channels: 0,
      notification_lang: '',
    });
    expect(errors.score_threshold).toBeTruthy();
    expect(errors.min_channels).toBeTruthy();
    expect(errors.notification_lang).toBeTruthy();
  });
});
