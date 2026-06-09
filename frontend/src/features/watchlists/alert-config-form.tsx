/**
 * AlertConfigForm — sub-form for alert_config fields.
 *
 * Fields (from gen.types AlertConfig):
 *  - score_threshold: number (0..100) — scoring threshold for an alert
 *  - min_channels:    number (≥1)    — cross-channel corroboration count
 *  - notification_lang: string (ISO-639-1) — default "en"
 *
 * Ranges/constraints from the backend schema, not magic literals.
 * Supports field-level error display for server 422 responses.
 * a11y: labels, aria-describedby, aria-invalid, error regions accessible.
 *
 * NOTE: validateAlertConfig lives in alert-config-validation.ts to comply
 * with react-refresh/only-export-components (file exports only a component).
 */

import React from 'react';
import { Label } from '@/shared/components/label';
import { Input } from '@/shared/components/input';
import type { AlertConfig } from '@/entities/watchlist/model';

// ISO-639-1 language options — limited to common set; server validates exhaustively.
// These are display options only; unknown lang will produce a server 422 inline error.
const SUPPORTED_LANGS = [
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Russian' },
  { value: 'de', label: 'German' },
  { value: 'fr', label: 'French' },
  { value: 'es', label: 'Spanish' },
  { value: 'zh', label: 'Chinese' },
  { value: 'ar', label: 'Arabic' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'it', label: 'Italian' },
  { value: 'ja', label: 'Japanese' },
] as const;

export interface AlertConfigFieldErrors {
  score_threshold?: string;
  min_channels?: string;
  notification_lang?: string;
  'alert_config.score_threshold'?: string;
  'alert_config.min_channels'?: string;
  'alert_config.notification_lang'?: string;
}

export interface AlertConfigFormProps {
  value: AlertConfig;
  onChange: (value: AlertConfig) => void;
  fieldErrors?: AlertConfigFieldErrors;
  disabled?: boolean;
}

export const AlertConfigForm: React.FC<AlertConfigFormProps> = ({
  value,
  onChange,
  fieldErrors,
  disabled,
}) => {
  const handleScoreChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const num = Number(e.target.value);
    onChange({ ...value, score_threshold: isNaN(num) ? 0 : num });
  };

  const handleMinChannelsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const num = Number(e.target.value);
    onChange({ ...value, min_channels: isNaN(num) ? 1 : num });
  };

  const handleLangChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    onChange({ ...value, notification_lang: e.target.value });
  };

  // Normalise server field paths (alert_config.X → X)
  const scoreError =
    fieldErrors?.score_threshold ??
    fieldErrors?.['alert_config.score_threshold'];
  const minChError =
    fieldErrors?.min_channels ??
    fieldErrors?.['alert_config.min_channels'];
  const langError =
    fieldErrors?.notification_lang ??
    fieldErrors?.['alert_config.notification_lang'];

  return (
    <fieldset className="flex flex-col gap-4 border border-border rounded-md p-4" disabled={disabled}>
      <legend className="text-sm font-medium px-1">Alert configuration</legend>

      {/* score_threshold */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="alert-score-threshold">
          Score threshold
        </Label>
        <Input
          id="alert-score-threshold"
          type="number"
          min={0}
          max={100}
          step={1}
          value={value.score_threshold}
          onChange={handleScoreChange}
          disabled={disabled}
          aria-invalid={!!scoreError}
          aria-describedby={scoreError ? 'alert-score-threshold-error' : undefined}
          placeholder="0–100"
        />
        {scoreError && (
          <p
            id="alert-score-threshold-error"
            role="alert"
            className="text-xs text-destructive"
          >
            {scoreError}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Minimum virality score (0–100) to trigger an alert. Higher = fewer, more viral alerts.
        </p>
      </div>

      {/* min_channels */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="alert-min-channels">
          Min channels
        </Label>
        <Input
          id="alert-min-channels"
          type="number"
          min={1}
          step={1}
          value={value.min_channels}
          onChange={handleMinChannelsChange}
          disabled={disabled}
          aria-invalid={!!minChError}
          aria-describedby={minChError ? 'alert-min-channels-error' : 'alert-min-channels-hint'}
          placeholder="≥ 1"
        />
        {minChError ? (
          <p
            id="alert-min-channels-error"
            role="alert"
            className="text-xs text-destructive"
          >
            {minChError}
          </p>
        ) : (
          <p
            id="alert-min-channels-hint"
            className="text-xs text-muted-foreground"
          >
            Cross-channel corroboration: how many channels must carry the story.
            This is a scoring parameter, not the number of channels in this watchlist
            (one watchlist = one channel).
          </p>
        )}
      </div>

      {/* notification_lang */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="alert-notification-lang">
          Notification language
        </Label>
        {/* Native select — accessible, responsive */}
        <select
          id="alert-notification-lang"
          value={value.notification_lang}
          onChange={handleLangChange}
          disabled={disabled}
          aria-invalid={!!langError}
          aria-describedby={langError ? 'alert-notification-lang-error' : undefined}
          className="border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50"
        >
          {SUPPORTED_LANGS.map((lang) => (
            <option key={lang.value} value={lang.value}>
              {lang.label} ({lang.value})
            </option>
          ))}
        </select>
        {langError && (
          <p
            id="alert-notification-lang-error"
            role="alert"
            className="text-xs text-destructive"
          >
            {langError}
          </p>
        )}
      </div>
    </fieldset>
  );
};
