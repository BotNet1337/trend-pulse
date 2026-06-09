/**
 * WatchlistDetailPage — /watchlists/:watchlistId
 *
 * Shows details + edit form for a single watchlist.
 * PATCH /watchlists/{id} → saves; DELETE handled from list.
 * 404 → not-found state (doesn't leak existence of other tenants' data).
 */

import React, { useState } from 'react';
import { useNavigate, useParams, Link } from '@tanstack/react-router';
import { useWatchlist, useUpdateWatchlist, AlertConfigForm } from '@/features/watchlists';
import { validateAlertConfig } from '@/features/watchlists';
import { Button } from '@/shared/components/button';
import { Input } from '@/shared/components/input';
import { Label } from '@/shared/components/label';
import { mapBackendError } from '@/shared/lib';
import type { BackendErrorState } from '@/shared/lib';
import type { AlertConfig, WatchlistRead } from '@/entities/watchlist/model';
import { BRAND_NAME } from '@/shared/config';
import { UpsellBanner } from '@/shared/components/upsell-banner';
import { useCurrentUser } from '@/entities/viewer/model';

// ─── Inner edit form — receives watchlist as prop so useState can be initialised ──────
// This avoids using useEffect + setState for async data, which violates the lint rule.

interface EditFormProps {
  watchlist: WatchlistRead;
  onSaved: () => void;
}

const WatchlistEditForm: React.FC<EditFormProps> = ({ watchlist, onSaved }) => {
  const { data: currentUser } = useCurrentUser();
  const updateMutation = useUpdateWatchlist(watchlist.id);

  // State initialised directly from prop — no useEffect required
  const [handle, setHandle] = useState(watchlist.channel.handle);
  const [topic, setTopic] = useState(watchlist.topic);
  const [alertConfig, setAlertConfig] = useState<AlertConfig>(watchlist.alert_config);

  const [backendState, setBackendState] = useState<BackendErrorState | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const alertFieldErrors =
    backendState?.kind === 'field' ? backendState.fields : {};

  const handleFieldError =
    backendState?.kind === 'field'
      ? (backendState.fields['channel.handle'] ??
        backendState.fields['channel'] ??
        backendState.fields['handle'])
      : null;

  const topicFieldError =
    backendState?.kind === 'field' ? backendState.fields['topic'] : null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBackendState(null);
    setGeneralError(null);
    setSuccessMsg(null);

    const configErrors = validateAlertConfig(alertConfig);
    if (Object.keys(configErrors).length > 0) {
      setBackendState({
        kind: 'field',
        fields: configErrors as Record<string, string>,
        message: 'Please fix the alert configuration fields.',
      });
      return;
    }

    try {
      await updateMutation.mutateAsync({
        topic: topic.trim() || undefined,
        channel: { handle, kind: 'telegram' },
        alert_config: alertConfig,
      });
      setSuccessMsg('Watchlist updated.');
      onSaved();
    } catch (err: unknown) {
      const state = mapBackendError(err);
      if (state.kind === 'quota' || state.kind === 'feature-gate' || state.kind === 'field') {
        setBackendState(state);
      } else {
        setGeneralError(state.message);
      }
    }
  };

  const pending = updateMutation.isPending;

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-6" noValidate>
      {/* 402 upsell */}
      {backendState?.kind === 'quota' && (
        <UpsellBanner message={backendState.message} currentPlan={currentUser?.plan} />
      )}

      {/* 403 feature gate */}
      {backendState?.kind === 'feature-gate' && (
        <div
          role="alert"
          className="rounded-lg border border-border bg-muted px-4 py-3 text-sm"
        >
          <p className="font-medium">Feature not available</p>
          <p className="text-muted-foreground mt-1">{backendState.message}</p>
        </div>
      )}

      {generalError && (
        <p role="alert" className="text-sm text-destructive">
          {generalError}
        </p>
      )}

      {successMsg && (
        <p role="status" className="text-sm text-green-700 dark:text-green-400">
          {successMsg}
        </p>
      )}

      {/* Channel handle */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="edit-channel-handle">Channel handle</Label>
        <Input
          id="edit-channel-handle"
          type="text"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          placeholder="@channelname"
          disabled={pending}
          aria-invalid={!!handleFieldError}
          aria-describedby={handleFieldError ? 'edit-channel-handle-error' : undefined}
        />
        {handleFieldError && (
          <p
            id="edit-channel-handle-error"
            role="alert"
            className="text-xs text-destructive"
          >
            {handleFieldError}
          </p>
        )}
      </div>

      {/* Topic */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="edit-watchlist-topic">Topic</Label>
        <Input
          id="edit-watchlist-topic"
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. bitcoin"
          disabled={pending}
          aria-invalid={!!topicFieldError}
          aria-describedby={topicFieldError ? 'edit-watchlist-topic-error' : undefined}
        />
        {topicFieldError && (
          <p
            id="edit-watchlist-topic-error"
            role="alert"
            className="text-xs text-destructive"
          >
            {topicFieldError}
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
          {pending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
};

// ─── Page shell ───────────────────────────────────────────────────────────────

export const WatchlistDetailPage: React.FC = () => {
  const navigate = useNavigate();
  const { watchlistId } = useParams({ strict: false }) as { watchlistId?: string };
  const id = watchlistId ? parseInt(watchlistId, 10) : NaN;

  const { data: watchlist, isLoading, error } = useWatchlist(id);

  const handleSaved = () => {
    // Stay on page — success message shown by form
  };

  // 404 or bad id
  const is404 =
    (error as { response?: { status?: number } })?.response?.status === 404 ||
    isNaN(id);

  if (is404) {
    return (
      <div className="auth-light min-h-dvh flex flex-col bg-background text-foreground">
        <header className="border-b border-border px-6 py-3 flex items-center gap-3">
          <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
          <Link
            to="/watchlists"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Back to watchlists
          </Link>
        </header>
        <main className="flex-1 container max-w-xl mx-auto px-4 py-16 text-center">
          <h1 className="text-xl font-semibold mb-2">Watchlist not found</h1>
          <p className="text-muted-foreground text-sm mb-6">
            This watchlist does not exist or you do not have access to it.
          </p>
          <Button type="button" onClick={() => void navigate({ to: '/watchlists' })}>
            Back to watchlists
          </Button>
        </main>
      </div>
    );
  }

  return (
    <div className="auth-light min-h-dvh flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <Link
          to="/watchlists"
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Back to watchlists
        </Link>
      </header>

      <main className="flex-1 container max-w-xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-6">Edit watchlist</h1>

        {isLoading && (
          <div aria-busy="true" className="flex justify-center py-16">
            <span className="text-muted-foreground text-sm">Loading…</span>
          </div>
        )}

        {!isLoading && error && !is404 && (
          <p role="alert" className="text-sm text-destructive mb-4">
            Failed to load watchlist. Please refresh.
          </p>
        )}

        {/* Render edit form once watchlist data is available */}
        {!isLoading && watchlist && (
          <WatchlistEditForm watchlist={watchlist} onSaved={handleSaved} />
        )}
      </main>
    </div>
  );
};
