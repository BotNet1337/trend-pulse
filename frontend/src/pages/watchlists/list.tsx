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
import { PacksBlock } from '@/features/packs';
import { WatchlistCard } from '@/entities/watchlist';
import { Button } from '@/shared/components/button';
import { EmptyState } from '@/shared/components/empty-state';

export const WatchlistsListPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: watchlists, isLoading, error } = useWatchlists();
  const deleteMutation = useDeleteWatchlist();
  const [deleteError, setDeleteError] = useState<string | null>(null);

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

  return (
    <main className="fs-main">
      <div className="mx-auto max-w-3xl px-4">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Watchlists</h1>
          <Button type="button" onClick={handleCreate}>
            Add watchlist
          </Button>
        </div>

        {deleteError && (
          <p role="alert" className="mb-4 text-sm text-destructive">
            {deleteError}
          </p>
        )}

        {isLoading && (
          <div aria-busy="true" aria-label="Loading watchlists" className="flex justify-center py-16">
            <span className="text-muted-foreground text-sm">Loading…</span>
          </div>
        )}

        {!isLoading && error && (
          <p role="alert" className="text-sm text-destructive">
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
          <ul className="flex flex-col gap-4" aria-label="Your watchlists">
            {watchlists.map((wl) => (
              <li key={wl.id}>
                <WatchlistCard
                  watchlist={wl}
                  onEdit={handleEdit}
                  onDelete={(id) => void handleDelete(id)}
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
    </main>
  );
};
