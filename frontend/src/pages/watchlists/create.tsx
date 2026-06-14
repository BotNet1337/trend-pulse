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
      <div className="mx-auto max-w-xl px-4">
        <h1 className="text-2xl font-bold mb-6">New watchlist</h1>

        {/* 402 upsell banner */}
        {backendState?.kind === 'quota' && (
          <div className="mb-6">
            <UpsellBanner
              message={backendState.message}
              currentPlan={currentUser?.plan}
            />
          </div>
        )}

        {/* 403 feature gate */}
        {backendState?.kind === 'feature-gate' && (
          <div
            role="alert"
            className="mb-6 rounded-lg border border-border bg-muted px-4 py-3 text-sm"
          >
            <p className="font-medium">Feature not available</p>
            <p className="text-muted-foreground mt-1">{backendState.message}</p>
            <Link to={paths.account.settings} className="underline mt-2 inline-block">
              View account settings
            </Link>
          </div>
        )}

        {/* 409 duplicate / generic error */}
        {generalError && (
          <p role="alert" className="mb-4 text-sm text-destructive">
            {generalError}
          </p>
        )}

        <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-6" noValidate>
          {/* Channel handle */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="channel-handle">Channel handle</Label>
            <Input
              id="channel-handle"
              type="text"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="@channelname"
              autoComplete="off"
              disabled={pending}
              aria-invalid={!!(handleError ?? handleFieldErrors)}
              aria-describedby={
                (handleError ?? handleFieldErrors)
                  ? 'channel-handle-error'
                  : 'channel-handle-hint'
              }
              required
            />
            {(handleError ?? handleFieldErrors) ? (
              <p
                id="channel-handle-error"
                role="alert"
                className="text-xs text-destructive"
              >
                {handleError ?? handleFieldErrors}
              </p>
            ) : (
              <p id="channel-handle-hint" className="text-xs text-muted-foreground">
                Public Telegram channel handle starting with @ (e.g. @mychannel)
              </p>
            )}
          </div>

          {/* Topic */}
          <div className="flex flex-col gap-1.5">
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
              <p
                id="watchlist-topic-error"
                role="alert"
                className="text-xs text-destructive"
              >
                {topicError ?? topicFieldError}
              </p>
            )}
          </div>

          {/* Alert config */}
          <AlertConfigForm
            value={alertConfig}
            onChange={setAlertConfig}
            fieldErrors={alertFieldErrors}
            disabled={pending}
          />

          <div className="flex gap-3">
            <Button type="submit" disabled={pending} className="flex-1">
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
