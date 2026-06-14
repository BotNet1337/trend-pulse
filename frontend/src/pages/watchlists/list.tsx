/**
 * WatchlistsListPage — /watchlists ("Signal Desk" redesign, TASK-095)
 *
 * Dense, sortable signal table of the caller's watchlists (GET /watchlists).
 * Toolbar: search + status segment + density toggle (all client-side UI state).
 * Per-row quick actions (view / edit / delete) reuse the existing handlers and
 * mutations — behaviour, data, routes and query keys are unchanged. Signal
 * columns the backend does not provide yet (sparkline, ×baseline velocity,
 * last-alert) degrade to neutral placeholders; no fabricated data.
 *
 * Empty/first-run state explains what a watchlist is + curated channel packs.
 * A plan-usage banner surfaces the Free → Pro upsell using real plan limits.
 */

import React, { useMemo, useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Link } from '@tanstack/react-router';
import { useWatchlists, useDeleteWatchlist } from '@/features/watchlists';
import {
  WatchlistRow,
  WatchlistsToolbar,
  selectVisibleWatchlists,
  ariaSortFor,
  nextSort,
  type DeskStatus,
  type DeskDensity,
  type DeskSort,
  type DeskSortKey,
} from '@/features/watchlists';
import { PacksBlock } from '@/features/packs';
import { useCurrentUser } from '@/entities/viewer/model';
import {
  PLAN_FREE,
  PLAN_MAX_WATCHLISTS,
  PLAN_DISPLAY_NAME,
  type PlanId,
} from '@/entities/plan';
import { Button } from '@/shared/components/button';

/** Sort caret SVG. */
const Caret: React.FC = () => (
  <svg className="caret" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m6 9 6 6 6-6" />
  </svg>
);

interface SortableHeaderProps {
  column: DeskSortKey;
  label: string;
  sort: DeskSort;
  onSort: (column: DeskSortKey) => void;
}

const SortableHeader: React.FC<SortableHeaderProps> = ({ column, label, sort, onSort }) => (
  <th scope="col" aria-sort={ariaSortFor(column, sort)}>
    <button type="button" className="sort" onClick={() => onSort(column)}>
      {label}
      <Caret />
    </button>
  </th>
);

export const WatchlistsListPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: watchlists, isLoading, error } = useWatchlists();
  const { data: currentUser } = useCurrentUser();
  const deleteMutation = useDeleteWatchlist();
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // ── Client-side desk UI state (visual only) ──────────────────────────────
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<DeskStatus>('all');
  const [density, setDensity] = useState<DeskDensity>('comfortable');
  const [sort, setSort] = useState<DeskSort>({ key: 'threshold', dir: 'desc' });

  const handleSort = (column: DeskSortKey) => {
    setSort((current) => nextSort(current, column));
  };

  const handleView = (id: number) => {
    void navigate({ to: '/watchlists/$watchlistId', params: { watchlistId: String(id) } });
  };

  const handleEdit = (id: number) => {
    void navigate({ to: '/watchlists/$watchlistId', params: { watchlistId: String(id) } });
  };

  const handleDelete = async (id: number) => {
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(id);
    } catch {
      setDeleteError('Failed to delete watchlist. Please try again.');
    }
  };

  const handleCreate = () => {
    void navigate({ to: '/watchlists/new' });
  };

  const visible = useMemo(
    () => selectVisibleWatchlists(watchlists ?? [], { query, status, sort }),
    [watchlists, query, status, sort],
  );

  const total = watchlists?.length ?? 0;
  const hasWatchlists = total > 0;

  // Plan usage for the upsell — real plan limit, no invented numbers.
  const plan = (currentUser?.plan ?? PLAN_FREE) as PlanId;
  const planMax = PLAN_MAX_WATCHLISTS[plan] ?? 0;
  const planName = PLAN_DISPLAY_NAME[plan] ?? currentUser?.plan ?? 'Free';
  const atOrOverLimit = planMax > 0 && total >= planMax;
  // Show the upsell when the Free plan can't hold own watchlists, or when a
  // paid plan is at/over its channel limit.
  const showUpsell = plan === PLAN_FREE || atOrOverLimit;
  const usagePercent = planMax > 0 ? Math.min(100, Math.round((total / planMax) * 100)) : 100;

  return (
    <main className={`fs-main${density === 'compact' ? ' is-compact' : ''}`}>
      <div className="fs-container">
        <div className="fs-page-head">
          <div>
            <h1 className="fs-page-head__title">Watchlists</h1>
            <p className="fs-page-head__sub">
              Live virality desk — your tracked channels and topics.
            </p>
          </div>
          <div className="fs-page-head__actions">
            <Button type="button" onClick={handleCreate}>
              Add watchlist
            </Button>
          </div>
        </div>

        {showUpsell && (
          <aside className="fs-card fs-upsell" aria-label="Plan usage">
            <div>
              <p className="fs-upsell__title">
                You're on the <strong>{planName} plan</strong>
                {planMax > 0 ? ` — ${total} of ${planMax} channels used` : ''}
              </p>
              <p className="fs-upsell__text">
                Pro unlocks more tracked channels, faster polling, and cross-channel
                origin tracing.
              </p>
              <div
                className="fs-upsell__meter"
                role="img"
                aria-label={planMax > 0 ? `${total} of ${planMax} channels used` : 'Plan usage'}
              >
                <span style={{ width: `${usagePercent}%` }} />
              </div>
            </div>
            <div className="fs-upsell__actions">
              <Link to="/billing" className="fs-btn fs-btn--ghost fs-btn--sm">
                Compare plans
              </Link>
              <Link
                to="/billing"
                className="fs-btn fs-btn--primary fs-btn--sm"
                aria-label="Upgrade your plan"
              >
                Upgrade to Pro
              </Link>
            </div>
          </aside>
        )}

        {deleteError && (
          <p role="alert" className="fs-error fs-mt-0" style={{ marginBottom: '1rem' }}>
            {deleteError}
          </p>
        )}

        {isLoading && (
          <div aria-busy="true" aria-label="Loading watchlists" className="fs-center" style={{ padding: '4rem 0' }}>
            <span className="fs-muted">Loading…</span>
          </div>
        )}

        {!isLoading && error && (
          <p role="alert" className="fs-error">
            Failed to load watchlists. Please refresh.
          </p>
        )}

        {!isLoading && !error && hasWatchlists && (
          <>
            <WatchlistsToolbar
              query={query}
              onQueryChange={setQuery}
              status={status}
              onStatusChange={setStatus}
              density={density}
              onDensityChange={setDensity}
            />

            <div className="desk-wrap">
              <div className="desk-scroll">
                <table className="desk-table" aria-label="Your watchlists, sortable">
                  <thead>
                    <tr>
                      <SortableHeader column="name" label="Watchlist" sort={sort} onSort={handleSort} />
                      <th scope="col">Live signal (24h)</th>
                      <SortableHeader column="sources" label="Sources" sort={sort} onSort={handleSort} />
                      <SortableHeader column="threshold" label="Threshold" sort={sort} onSort={handleSort} />
                      <th scope="col">Last alert</th>
                      <th scope="col">Status</th>
                      <th scope="col">
                        <span className="fs-sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((wl) => (
                      <WatchlistRow
                        key={wl.id}
                        watchlist={wl}
                        onView={handleView}
                        onEdit={handleEdit}
                        onDelete={(id) => void handleDelete(id)}
                        deleteIsPending={
                          deleteMutation.isPending && deleteMutation.variables === wl.id
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {visible.length === 0 && (
              <p className="fs-muted fs-center" style={{ padding: '2rem 0' }}>
                No watchlists match your filter.
              </p>
            )}

            <p className="legend" aria-hidden="true">
              <span>
                <span className="status-dot status-dot--active" /> Active
              </span>
              <span>
                <strong style={{ color: 'var(--fs-text-muted)' }}>Threshold</strong> = score a topic must hit to alert
              </span>
            </p>
          </>
        )}

        {!isLoading && !error && watchlists && !hasWatchlists && (
          <div className="desk-wrap">
            <div className="desk-empty">
              <div className="desk-empty__icon" aria-hidden="true">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 18v-2a4 4 0 0 1 4-4h2" />
                  <path d="m13 7 3 3 5-5" />
                  <circle cx="7" cy="8" r="3" />
                </svg>
              </div>
              <h2 className="desk-empty__title">Track your first topic</h2>
              <p className="desk-empty__text">
                A watchlist is a Telegram channel Foresignal watches for you. We alert the
                moment a topic's velocity spikes above its channel baseline. Start from a
                curated pack below or build one from scratch.
              </p>
              <Button type="button" onClick={handleCreate}>
                Create watchlist
              </Button>
            </div>
          </div>
        )}

        {/* Curated channel packs block (TASK-038) */}
        <PacksBlock />
      </div>
    </main>
  );
};
