/**
 * WatchlistsToolbar — search + status segment + density toggle for the Signal
 * Desk. Pure presentation: it owns no data, only reflects/raises local UI state
 * (TASK-095). All controls are client-side; nothing here touches the API.
 */

import React from 'react';
import type { DeskStatus, DeskDensity } from './signal-desk';

interface WatchlistsToolbarProps {
  query: string;
  onQueryChange: (value: string) => void;
  status: DeskStatus;
  onStatusChange: (value: DeskStatus) => void;
  density: DeskDensity;
  onDensityChange: (value: DeskDensity) => void;
}

const STATUS_OPTIONS: ReadonlyArray<{ value: DeskStatus; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
];

export const WatchlistsToolbar: React.FC<WatchlistsToolbarProps> = ({
  query,
  onQueryChange,
  status,
  onStatusChange,
  density,
  onDensityChange,
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

      <div className="desk-segment" role="group" aria-label="Status filter">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            aria-pressed={status === opt.value}
            onClick={() => onStatusChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="desk-segment" role="group" aria-label="Row density">
        <button
          type="button"
          aria-pressed={density === 'comfortable'}
          onClick={() => onDensityChange('comfortable')}
        >
          Comfortable
        </button>
        <button
          type="button"
          aria-pressed={density === 'compact'}
          onClick={() => onDensityChange('compact')}
        >
          Compact
        </button>
      </div>
    </div>
  );
};
