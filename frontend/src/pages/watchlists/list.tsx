/**
 * WatchlistsListPage — /watchlists
 *
 * Shows the user's watchlists (GET /watchlists).
 * Empty state with CTA when none exist.
 * Delete inline; each card links to edit.
 */

import React, { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useWatchlists, useDeleteWatchlist } from '@/features/watchlists';
import type { WatchlistRead } from '@/entities/watchlist';
import { PacksBlock } from '@/features/packs';
import { WatchlistCard } from '@/entities/watchlist';
import { Button } from '@/shared/components/button';
import { ConfirmDialog } from '@/shared/components/confirm-dialog';
import { EmptyState } from '@/shared/components/empty-state';

export const WatchlistsListPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: watchlists, isLoading, error } = useWatchlists();
  const deleteMutation = useDeleteWatchlist();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Watchlist pending deletion — non-null opens the confirmation dialog.
  const [deleteTarget, setDeleteTarget] = useState<WatchlistRead | null>(null);

  const handleEdit = (id: number) => {
    void navigate({ to: '/watchlists/$watchlistId', params: { watchlistId: String(id) } });
  };

  const requestDelete = (id: number) => {
    setDeleteError(null);
    setDeleteTarget(watchlists?.find((wl) => wl.id === id) ?? null);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch {
      setDeleteError('Failed to delete watchlist. Please try again.');
      setDeleteTarget(null);
    }
  };

  const handleCreate = () => {
    void navigate({ to: '/watchlists/new' });
  };

  return (
    <main className="fs-main">
      <div className="fs-container">
        <div className="fs-page-head">
          <h1 className="fs-page-head__title">Watchlists</h1>
          <div className="fs-page-head__actions">
            <Button type="button" onClick={handleCreate}>
              Add watchlist
            </Button>
          </div>
        </div>

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

        {!isLoading && !error && watchlists && watchlists.length === 0 && (
          <EmptyState
            title="No watchlists yet"
            description="Create your first watchlist to track a Telegram channel for viral content on a topic."
            ctaLabel="Create first watchlist"
            onCta={handleCreate}
          />
        )}

        {!isLoading && !error && watchlists && watchlists.length > 0 && (
          <ul className="fs-list" aria-label="Your watchlists">
            {watchlists.map((wl) => (
              <li key={wl.id}>
                <WatchlistCard
                  watchlist={wl}
                  onEdit={handleEdit}
                  onDelete={requestDelete}
                  deleteIsPending={
                    deleteMutation.isPending && deleteMutation.variables === wl.id
                  }
                />
              </li>
            ))}
          </ul>
        )}

        {/* Curated channel packs block (TASK-038) */}
        <PacksBlock />
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete watchlist?"
        description={
          deleteTarget
            ? `“${deleteTarget.channel.handle}” will stop being tracked. This cannot be undone.`
            : undefined
        }
        confirmLabel="Delete watchlist"
        pendingLabel="Deleting..."
        isPending={deleteMutation.isPending}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </main>
  );
};
