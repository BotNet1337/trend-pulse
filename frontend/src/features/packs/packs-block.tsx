/**
 * PacksBlock — «Channel packs» widget for the watchlists page.
 *
 * Shows the curated pack catalog with subscribe/unsubscribe buttons.
 * Handles:
 *   - Loading state
 *   - 402 → human-readable plan limit message
 *   - Subscribe / Unsubscribe with created/skipped feedback
 */

import React, { useState } from 'react';
import { usePacks, useSubscribePack, useUnsubscribePack } from './queries';
import type { PackRead } from './api';
import { extractErrorMessage } from './error-message';
import { Button } from '@/shared/components/button';

/** Manual EN pluralisation — no i18n framework (TASK-072 decision). */
const channelsWord = (count: number): string => (count === 1 ? 'channel' : 'channels');

interface PackRowProps {
  pack: PackRead;
}

const PackRow: React.FC<PackRowProps> = ({ pack }) => {
  const subscribeMutation = useSubscribePack();
  const unsubscribeMutation = useUnsubscribePack();
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubscribe = async () => {
    setFeedback(null);
    setError(null);
    try {
      const result = await subscribeMutation.mutateAsync(pack.slug);
      if (result.created === 0) {
        setFeedback(`Already connected (${result.skipped} ${channelsWord(result.skipped)} skipped)`);
      } else {
        setFeedback(
          `Connected: ${result.created} ${channelsWord(result.created)} added${result.skipped > 0 ? `, ${result.skipped} already present` : ''}`,
        );
      }
    } catch (err: unknown) {
      setError(extractErrorMessage(err));
    }
  };

  const handleUnsubscribe = async () => {
    setFeedback(null);
    setError(null);
    try {
      const result = await unsubscribeMutation.mutateAsync(pack.slug);
      setFeedback(`Disconnected: ${result.deleted} ${channelsWord(result.deleted)} removed`);
    } catch (err: unknown) {
      setError(extractErrorMessage(err));
    }
  };

  const isPending = subscribeMutation.isPending || unsubscribeMutation.isPending;

  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold text-sm">{pack.title}</span>
          <span className="text-xs text-muted-foreground">
            {pack.topic} &middot; {pack.channels_count} {channelsWord(pack.channels_count)}
          </span>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isPending}
            onClick={() => void handleSubscribe()}
            aria-label={`Connect pack ${pack.title}`}
          >
            {subscribeMutation.isPending ? 'Connecting…' : 'Connect'}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={isPending}
            onClick={() => void handleUnsubscribe()}
            aria-label={`Disconnect pack ${pack.title}`}
          >
            {unsubscribeMutation.isPending ? 'Disconnecting…' : 'Disconnect'}
          </Button>
        </div>
      </div>
      {feedback && (
        <p className="text-xs text-muted-foreground mt-1" aria-live="polite">
          {feedback}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive mt-1">
          {error}
        </p>
      )}
    </li>
  );
};

/** «Channel packs» block — rendered on the watchlists list page. */
export const PacksBlock: React.FC = () => {
  const { data: packs, isLoading, error } = usePacks();

  return (
    <section aria-labelledby="packs-heading" className="mt-10">
      <h2 id="packs-heading" className="text-xl font-bold mb-4">
        Channel packs
      </h2>
      <p className="text-sm text-muted-foreground mb-4">
        Curated channel collections — connect in one click. They do not count toward your channel limit.
      </p>

      {isLoading && (
        <div aria-busy="true" aria-label="Loading packs" className="py-8 flex justify-center">
          <span className="text-sm text-muted-foreground">Loading…</span>
        </div>
      )}

      {!isLoading && error && (
        <p role="alert" className="text-sm text-destructive">
          Failed to load packs. Please refresh the page.
        </p>
      )}

      {!isLoading && !error && packs && packs.length === 0 && (
        <p className="text-sm text-muted-foreground">The pack catalog is empty.</p>
      )}

      {!isLoading && !error && packs && packs.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="Pack catalog">
          {packs.map((pack) => (
            <PackRow key={pack.slug} pack={pack} />
          ))}
        </ul>
      )}
    </section>
  );
};
