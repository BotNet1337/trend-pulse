/**
 * WatchlistsListPage — /watchlists
 *
 * Shows the user's watchlists (GET /watchlists).
 * Empty state with CTA when none exist.
 * Delete inline; each card links to edit.
 */

import React, { useState } from 'react';
import { useNavigate, Link } from '@tanstack/react-router';
import { useWatchlists, useDeleteWatchlist } from '@/features/watchlists';
import { WatchlistCard } from '@/entities/watchlist';
import { Button } from '@/shared/components/button';
import { EmptyState } from '@/shared/components/empty-state';
import { BRAND_NAME } from '@/shared/config';
import { useLogout } from '@/features/auth';
import { paths } from '@/app/router/path';

export const WatchlistsListPage: React.FC = () => {
  const navigate = useNavigate();
  const logoutMutation = useLogout();
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
    <div className="auth-light min-h-dvh flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <nav className="flex items-center gap-3 text-sm">
          <Link
            to={paths.account.settings}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Settings
          </Link>
        </nav>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={logoutMutation.isPending}
          onClick={() => logoutMutation.mutate()}
          aria-label="Sign out"
        >
          {logoutMutation.isPending ? 'Signing out…' : 'Sign out'}
        </Button>
      </header>

      <main className="flex-1 container max-w-3xl mx-auto px-4 py-8">
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
      </main>
    </div>
  );
};
