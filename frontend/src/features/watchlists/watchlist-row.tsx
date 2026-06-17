/**
 * WatchlistRow — one row of the Signal Desk table (`/watchlists`).
 *
 * Renders a watchlist with the SAME edit/delete handlers the previous card used,
 * plus the live `signal` (TASK-096): a real 24h sparkline and the live-signal
 * badge. The PRIMARY badge is the viral_score (`live_score`, 0-100) with a
 * hot/warm/calm tier colour (TASK-121); velocity is demoted to the badge tooltip
 * (kept for the API contract, not removed). Every signal field is graceful —
 * when the backend has no data the column falls back to its neutral placeholder;
 * no fabricated values, no pause action (no pause endpoint).
 */

import React from 'react';
import type { WatchlistRead } from '@/entities/watchlist';
import {
  sourcesCount,
  thresholdBarPercent,
  rowSignal,
  scoreTier,
  formatScoreBadge,
  formatSignalTooltip,
  formatIndependenceBadge,
  formatIndependenceTooltip,
  hasSparkline,
  sparklinePoints,
  formatLastAlert,
} from './signal-desk';

// Sparkline SVG canvas (matches the `.spark svg` CSS box and the placeholder viewBox).
const SPARK_WIDTH = 76;
const SPARK_HEIGHT = 26;
// Draw the line within an inset band so the stroke is never clipped at the edges.
const SPARK_INSET = 6;

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

  // Live signal (TASK-096) — every field graceful-empty when there is no data.
  // Primary badge = viral_score (TASK-121); velocity is kept for the tooltip.
  const signal = rowSignal(watchlist);
  const score = signal.live_score;
  const velocity = signal.live_velocity;
  const tier = scoreTier(score);
  const scoreLabel = formatScoreBadge(score);
  const signalTooltip = formatSignalTooltip(score, velocity);
  const sparklineSeries = signal.sparkline_24h ?? [];
  const sparklineOn = hasSparkline(sparklineSeries);
  const sparkPoints = sparklinePoints(
    sparklineSeries,
    SPARK_WIDTH - SPARK_INSET * 2,
    SPARK_HEIGHT - SPARK_INSET * 2,
  );
  const lastAlertLabel = formatLastAlert(signal.last_alert_at);

  // Source-independence chip (TASK-126): shown ONLY when effective_sources is real
  // and >= MIN_INDEPENDENCE_DISPLAY (single-source ~1 is hidden). Honest tooltip:
  // organic-spread signal, NOT a coordination verdict.
  const effectiveSources = signal.effective_sources;
  const independenceLabel = formatIndependenceBadge(effectiveSources);
  const independenceTooltip =
    // `effectiveSources != null` is for TypeScript narrowing only — it is logically
    // implied by `independenceLabel !== null` (a non-null label requires a real value).
    independenceLabel !== null && effectiveSources != null
      ? formatIndependenceTooltip(effectiveSources)
      : undefined;

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
      {/* Live signal: real 24h sparkline + viral_score badge (velocity in tooltip), graceful placeholder when empty. */}
      <td>
        <div className="spark">
          <svg
            className={sparklineOn ? 'spark__line' : 'spark__placeholder'}
            viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
            fill="none"
            aria-hidden="true"
          >
            {sparklineOn ? (
              <g transform={`translate(${SPARK_INSET} ${SPARK_INSET})`}>
                <polyline
                  points={sparkPoints}
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </g>
            ) : (
              <polyline
                points="0,14 12,14 24,14 36,14 48,14 60,14 76,14"
                stroke="var(--fs-text-faint)"
                strokeWidth="2"
                strokeDasharray="3 3"
                strokeLinecap="round"
              />
            )}
          </svg>
          {scoreLabel !== null ? (
            <span className={`vel-badge ${tier}`} title={signalTooltip}>
              {scoreLabel}
            </span>
          ) : (
            <span className="vel-badge vel-badge--empty" title={signalTooltip}>
              no signal
            </span>
          )}
          {independenceLabel !== null && (
            <span className="vel-badge vel-badge--independence" title={independenceTooltip}>
              {independenceLabel}
            </span>
          )}
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
      {/* Last alert: real timestamp when present, neutral placeholder otherwise. */}
      <td>
        {lastAlertLabel !== null ? (
          <span className="cell-mute" title={signal.last_alert_at ?? undefined}>
            {lastAlertLabel}
          </span>
        ) : (
          <span className="cell-mute">—</span>
        )}
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
