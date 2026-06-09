/**
 * Alert config validation helpers — separated from the form component so that
 * they can be imported by tests and other modules without triggering the
 * react-refresh/only-export-components rule.
 */

import type { AlertConfig } from '@/entities/watchlist/model';
import type { AlertConfigFieldErrors } from './alert-config-form';

/**
 * Client-side validation of alert config values.
 * Returns a map of field → error string; empty means valid.
 * Backend 422 is the authoritative gate — this is UX fast-feedback only.
 */
export function validateAlertConfig(value: AlertConfig): AlertConfigFieldErrors {
  const errors: AlertConfigFieldErrors = {};

  const threshold = Number(value.score_threshold);
  if (isNaN(threshold) || threshold < 0 || threshold > 100) {
    errors.score_threshold = 'Score threshold must be between 0 and 100';
  }

  const minCh = Number(value.min_channels);
  if (isNaN(minCh) || minCh < 1 || !Number.isInteger(minCh)) {
    errors.min_channels = 'Min channels must be a whole number ≥ 1';
  }

  if (!value.notification_lang || value.notification_lang.trim().length === 0) {
    errors.notification_lang = 'Notification language is required';
  }

  return errors;
}
