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
    <li>
      <article className="fs-card fs-card--pad-sm">
        <div className="fs-list__row">
          <div className="fs-list__main">
            <span className="fs-list__title">{pack.title}</span>
            <span className="fs-list__sub">
              {pack.topic} &middot; {pack.channels_count} {channelsWord(pack.channels_count)}
            </span>
          </div>
          <div className="fs-list__actions">
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
          <p className="fs-list__sub fs-mt-1" aria-live="polite" style={{ marginBottom: 0 }}>
            {feedback}
          </p>
        )}
        {error && (
          <p role="alert" className="fs-error fs-mt-1">
            {error}
          </p>
        )}
      </article>
    </li>
  );
};

/** «Channel packs» block — rendered on the watchlists list page. */
export const PacksBlock: React.FC = () => {
  const { data: packs, isLoading, error } = usePacks();

  return (
    <section aria-labelledby="packs-heading" className="fs-section">
      <h2 id="packs-heading" style={{ fontSize: '1.2rem' }}>
        Channel packs
      </h2>
      <p className="packs-intro">
        Curated channel collections — connect in one click. They do not count toward your channel limit.
      </p>

      {isLoading && (
        <div aria-busy="true" aria-label="Loading packs" className="fs-center" style={{ padding: '2rem 0' }}>
          <span className="fs-muted">Loading…</span>
        </div>
      )}

      {!isLoading && error && (
        <p role="alert" className="fs-error">
          Failed to load packs. Please refresh the page.
        </p>
      )}

      {!isLoading && !error && packs && packs.length === 0 && (
        <p className="fs-muted">The pack catalog is empty.</p>
      )}

      {!isLoading && !error && packs && packs.length > 0 && (
        <ul className="fs-list" aria-label="Pack catalog">
          {packs.map((pack) => (
            <PackRow key={pack.slug} pack={pack} />
          ))}
        </ul>
      )}
    </section>
  );
};
