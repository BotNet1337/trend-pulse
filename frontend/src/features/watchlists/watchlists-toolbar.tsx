/**
 * WatchlistsToolbar — search box for the Signal Desk. Pure presentation: owns no
 * data, only reflects/raises the local query state.
 *
 * The status segment (All/Active) and density toggle were removed: the backend
 * model has no status/pause field (every watchlist is always active) and the desk
 * now renders in a single compact format, so those controls filtered/changed
 * nothing.
 */

import React from 'react';

interface WatchlistsToolbarProps {
  query: string;
  onQueryChange: (value: string) => void;
}

export const WatchlistsToolbar: React.FC<WatchlistsToolbarProps> = ({
  query,
  onQueryChange,
}) => {
  return (
    <div className="desk-toolbar" role="search">
      <label className="desk-search">
        <span className="fs-sr-only">Filter watchlists</span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter by name or topic…"
        />
      </label>
    </div>
  );
};
