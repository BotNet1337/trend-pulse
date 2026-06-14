/**
 * WatchlistCreatePage — /watchlists/new
 *
 * Form: channel handle + topic + alert-config.
 * POST /watchlists → 201 → redirect to list.
 * Error handling: 402 → upsell, 403 → feature-gate, 422 → field errors, 409 → dup.
 */

import React, { useState } from 'react';
import { useNavigate, Link } from '@tanstack/react-router';
import { useCreateWatchlist, AlertConfigForm, validateAlertConfig } from '@/features/watchlists';
import { UpsellBanner } from '@/shared/components/upsell-banner';
import { Button } from '@/shared/components/button';
import { Input } from '@/shared/components/input';
import { Label } from '@/shared/components/label';
import { mapBackendError, validateHandleFormat } from '@/shared/lib';
import type { BackendErrorState } from '@/shared/lib';
import type { AlertConfig } from '@/entities/watchlist/model';
import { useCurrentUser } from '@/entities/viewer/model';
import { paths } from '@/app/router/path';

const DEFAULT_ALERT_CONFIG: AlertConfig = {
  score_threshold: 70,
  min_channels: 1,
  notification_lang: 'en',
};

export const WatchlistCreatePage: React.FC = () => {
  const navigate = useNavigate();
  const createMutation = useCreateWatchlist();
  const { data: currentUser } = useCurrentUser();

  const [handle, setHandle] = useState('');
  const [topic, setTopic] = useState('');
  const [alertConfig, setAlertConfig] = useState<AlertConfig>(DEFAULT_ALERT_CONFIG);

  const [handleError, setHandleError] = useState<string | null>(null);
  const [topicError, setTopicError] = useState<string | null>(null);
  const [backendState, setBackendState] = useState<BackendErrorState | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);

  // Extract field errors from backend 422 state
  const alertFieldErrors =
    backendState?.kind === 'field' ? backendState.fields : {};

  const handleFieldErrors =
    backendState?.kind === 'field'
      ? backendState.fields['channel.handle'] ??
        backendState.fields['channel'] ??
        backendState.fields['handle']
      : null;

  const topicFieldError =
    backendState?.kind === 'field' ? backendState.fields['topic'] : null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setHandleError(null);
    setTopicError(null);
    setBackendState(null);
    setGeneralError(null);

    // Client-side pre-validation
    const handleValidationError = validateHandleFormat(handle);
    if (handleValidationError) {
      setHandleError(handleValidationError);
      return;
    }

    if (!topic.trim()) {
      setTopicError('Topic is required');
      return;
    }

    const configErrors = validateAlertConfig(alertConfig);
    if (Object.keys(configErrors).length > 0) {
      // Show inline via alert config form — pass through state
      setBackendState({
        kind: 'field',
        fields: configErrors as Record<string, string>,
        message: 'Please fix the alert configuration fields.',
      });
      return;
    }

    try {
      await createMutation.mutateAsync({
        topic: topic.trim(),
        channel: { handle, kind: 'telegram' },
        alert_config: alertConfig,
      });
      void navigate({ to: '/watchlists' });
    } catch (error: unknown) {
      const state = mapBackendError(error);
      if (state.kind === 'quota' || state.kind === 'feature-gate') {
        setBackendState(state);
      } else if (state.kind === 'field') {
        setBackendState(state);
      } else if (state.kind === 'duplicate') {
        setBackendState(state);
        setGeneralError(state.message);
      } else if (state.kind === 'not-found') {
        setGeneralError(state.message);
      } else {
        setGeneralError(state.message);
      }
    }
  };

  const pending = createMutation.isPending;

  return (
    <main className="fs-main">
      <div className="fs-container" style={{ maxWidth: '640px' }}>
        <div className="fs-page-head">
          <h1 className="fs-page-head__title">New watchlist</h1>
        </div>

        {/* 402 upsell banner */}
        {backendState?.kind === 'quota' && (
          <div style={{ marginBottom: '1.5rem' }}>
            <UpsellBanner
              message={backendState.message}
              currentPlan={currentUser?.plan}
            />
          </div>
        )}

        {/* 403 feature gate */}
        {backendState?.kind === 'feature-gate' && (
          <div role="alert" className="fs-banner" style={{ marginBottom: '1.5rem', flexDirection: 'column' }}>
            <p className="fs-label">Feature not available</p>
            <p className="fs-muted fs-mt-0" style={{ marginTop: '0.25rem' }}>{backendState.message}</p>
            <Link to={paths.account.settings} className="fs-mt-1" style={{ display: 'inline-block' }}>
              View account settings
            </Link>
          </div>
        )}

        {/* 409 duplicate / generic error */}
        {generalError && (
          <p role="alert" className="fs-error" style={{ marginBottom: '1rem' }}>
            {generalError}
          </p>
        )}

        <form onSubmit={(e) => void onSubmit(e)} className="wl-form" noValidate>
          {/* Watchlist basics */}
          <section className="fs-card fs-form-section" aria-label="Watchlist">
            <div className="fs-form-section__body">
              {/* Channel handle */}
              <div className="fs-field">
                <Label htmlFor="channel-handle">Channel handle</Label>
                <Input
                  id="channel-handle"
                  type="text"
                  value={handle}
                  onChange={(e) => setHandle(e.target.value)}
                  placeholder="@channelname"
                  autoComplete="off"
                  disabled={pending}
                  className="fs-input--mono"
                  aria-invalid={!!(handleError ?? handleFieldErrors)}
                  aria-describedby={
                    (handleError ?? handleFieldErrors)
                      ? 'channel-handle-error'
                      : 'channel-handle-hint'
                  }
                  required
                />
                {(handleError ?? handleFieldErrors) ? (
                  <p id="channel-handle-error" role="alert" className="fs-error">
                    {handleError ?? handleFieldErrors}
                  </p>
                ) : (
                  <p id="channel-handle-hint" className="fs-hint">
                    Public Telegram channel handle starting with @ (e.g. @mychannel)
                  </p>
                )}
              </div>

              {/* Topic */}
              <div className="fs-field">
                <Label htmlFor="watchlist-topic">Topic</Label>
                <Input
                  id="watchlist-topic"
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. bitcoin, ukraine war"
                  disabled={pending}
                  aria-invalid={!!(topicError ?? topicFieldError)}
                  aria-describedby={
                    (topicError ?? topicFieldError) ? 'watchlist-topic-error' : undefined
                  }
                  required
                />
                {(topicError ?? topicFieldError) && (
                  <p id="watchlist-topic-error" role="alert" className="fs-error">
                    {topicError ?? topicFieldError}
                  </p>
                )}
              </div>
            </div>
          </section>

          {/* Alert config */}
          <AlertConfigForm
            value={alertConfig}
            onChange={setAlertConfig}
            fieldErrors={alertFieldErrors}
            disabled={pending}
          />

          <div className="wl-form-actions">
            <Button type="submit" disabled={pending}>
              {pending ? 'Creating…' : 'Create watchlist'}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void navigate({ to: '/watchlists' })}
              disabled={pending}
            >
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </main>
  );
};
