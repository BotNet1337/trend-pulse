/**
 * WatchlistRow — one row of the Signal Desk table (`/watchlists`).
 *
 * VISUAL ONLY: renders a watchlist with the SAME data and the SAME edit/delete
 * handlers the previous card used. Signal columns the backend does not provide
 * yet (24h sparkline series, live ×baseline velocity, last-alert) degrade to a
 * neutral placeholder — no fabricated values, no fabricated API calls (there is
 * no pause endpoint, so no pause action is rendered).
 */

import React from 'react';
import type { WatchlistRead } from '@/entities/watchlist';
import { sourcesCount, thresholdBarPercent } from './signal-desk';

interface WatchlistRowProps {
  watchlist: WatchlistRead;
  onView: (id: number) => void;
  onEdit: (id: number) => void;
  onDelete: (id: number) => void;
  deleteIsPending?: boolean;
}

/** Eye icon — view signals. */
const ViewIcon: React.FC = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const EditIcon: React.FC = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
  </svg>
);

const DeleteIcon: React.FC = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
  </svg>
);

export const WatchlistRow: React.FC<WatchlistRowProps> = ({
  watchlist,
  onView,
  onEdit,
  onDelete,
  deleteIsPending,
}) => {
  const { id, topic, channel, alert_config } = watchlist;
  const handle = channel.handle;
  const threshold = alert_config.score_threshold;
  const barPercent = thresholdBarPercent(threshold);
  const sources = sourcesCount(watchlist);

  return (
    <tr tabIndex={0} aria-label={`Watchlist ${handle} — ${topic}`}>
      <td>
        <div className="wl-name">
          <span className="status-dot status-dot--active" aria-hidden="true" />
          <span className="wl-name__txt">
            <span className="wl-name__title" title={handle}>
              {handle}
            </span>
            <span className="wl-name__topic" title={topic}>
              {topic}
            </span>
          </span>
        </div>
      </td>
      {/* Live signal: no backend series yet → neutral placeholder, not fake data. */}
      <td>
        <div className="spark">
          <svg className="spark__placeholder" viewBox="0 0 76 26" fill="none" aria-hidden="true">
            <polyline
              points="0,14 12,14 24,14 36,14 48,14 60,14 76,14"
              stroke="var(--fs-text-faint)"
              strokeWidth="2"
              strokeDasharray="3 3"
              strokeLinecap="round"
            />
          </svg>
          <span className="vel-badge calm" title="Live velocity data is not available yet">
            — no live data
          </span>
        </div>
      </td>
      <td>
        <span className="cell-num">{sources}</span>{' '}
        <span className="cell-mute">{sources === 1 ? 'channel' : 'channels'}</span>
      </td>
      <td>
        <span className="thr">
          <span className="thr__bar">
            <span style={{ width: `${barPercent}%` }} />
          </span>
          <span className="thr__num">{threshold}</span>
        </span>
      </td>
      {/* Last alert: no backend field → neutral placeholder. */}
      <td>
        <span className="cell-mute">—</span>
      </td>
      <td>
        <span className="cell-status">
          <span className="status-dot status-dot--active" aria-hidden="true" />
          Active
        </span>
      </td>
      <td>
        <div className="row-actions">
          <button
            className="icon-btn"
            type="button"
            onClick={() => onView(id)}
            aria-label={`View watchlist ${handle}`}
            title="View"
          >
            <ViewIcon />
          </button>
          <button
            className="icon-btn"
            type="button"
            onClick={() => onEdit(id)}
            aria-label={`Edit watchlist ${handle}`}
            title="Edit"
          >
            <EditIcon />
          </button>
          <button
            className="icon-btn icon-btn--danger"
            type="button"
            onClick={() => onDelete(id)}
            disabled={deleteIsPending}
            aria-label={`Delete watchlist ${handle}`}
            title="Delete"
          >
            <DeleteIcon />
          </button>
        </div>
      </td>
    </tr>
  );
};
