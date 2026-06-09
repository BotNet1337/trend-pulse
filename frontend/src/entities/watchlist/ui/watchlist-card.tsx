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
      className="border border-border rounded-lg p-4 flex flex-col gap-3 bg-card text-card-foreground"
      aria-label={`Watchlist: ${channel.handle} — ${topic}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1 min-w-0">
          {/* Handle rendered as text — JSX auto-escapes, no XSS risk */}
          <span
            className="font-mono text-sm font-medium text-foreground truncate"
            title={channel.handle}
          >
            {channel.handle}
          </span>
          {/* Topic rendered as text */}
          <span
            className="text-xs text-muted-foreground truncate"
            title={topic}
          >
            {topic}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
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

      <dl className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
        <div>
          <dt className="font-medium text-foreground/70">Score threshold</dt>
          <dd>{alert_config.score_threshold}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground/70">Min channels</dt>
          <dd>{alert_config.min_channels}</dd>
        </div>
        <div>
          <dt className="font-medium text-foreground/70">Language</dt>
          <dd>{alert_config.notification_lang}</dd>
        </div>
      </dl>
    </article>
  );
};
