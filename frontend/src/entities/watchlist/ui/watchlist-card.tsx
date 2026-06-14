/**
 * WatchlistCard — displays a single watchlist row in the list.
 * Renders channel handle, topic, and alert config summary.
 * Uses JSX auto-escape (no dangerouslySetInnerHTML) — XSS safe.
 */

import React from 'react';
import type { WatchlistRead } from '../model';
import { Button } from '@/shared/components/button';

interface WatchlistCardProps {
  watchlist: WatchlistRead;
  onEdit: (id: number) => void;
  onDelete: (id: number) => void;
  deleteIsPending?: boolean;
}

export const WatchlistCard: React.FC<WatchlistCardProps> = ({
  watchlist,
  onEdit,
  onDelete,
  deleteIsPending,
}) => {
  const { id, topic, channel, alert_config } = watchlist;

  return (
    <article
      className="fs-card wl-card"
      aria-label={`Watchlist: ${channel.handle} — ${topic}`}
    >
      <div className="fs-card__head">
        <div className="fs-list__main">
          {/* Handle rendered as text — JSX auto-escapes, no XSS risk */}
          <span
            className="fs-card__title fs-mono fs-truncate"
            title={channel.handle}
          >
            {channel.handle}
          </span>
          {/* Topic rendered as text */}
          <span className="fs-card__sub fs-truncate" title={topic}>
            {topic}
          </span>
        </div>

        <div className="fs-card__actions">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onEdit(id)}
            aria-label={`Edit watchlist ${channel.handle}`}
          >
            Edit
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => onDelete(id)}
            disabled={deleteIsPending}
            aria-label={`Delete watchlist ${channel.handle}`}
          >
            Delete
          </Button>
        </div>
      </div>

      <dl className="fs-meta">
        <div>
          <dt>Score threshold</dt>
          <dd>{alert_config.score_threshold}</dd>
        </div>
        <div>
          <dt>Min channels</dt>
          <dd>{alert_config.min_channels}</dd>
        </div>
        <div>
          <dt>Language</dt>
          <dd>{alert_config.notification_lang}</dd>
        </div>
      </dl>
    </article>
  );
};
