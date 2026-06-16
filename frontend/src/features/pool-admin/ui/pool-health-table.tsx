/**
 * PoolHealthTable (TASK-117) — per-account pool connection-status table.
 *
 * One row per account: index, a state badge (Connected/Cooling/Quarantined),
 * a cooldown for cooling accounts, and the last-error reason for quarantined
 * ones. A "stale" banner shows when the collector snapshot is missing/old.
 *
 * Styling mirrors the admin-metrics dashboard (`fs-*` / `fs-table` classes).
 */

import React from 'react';
import type { PoolHealthResponse } from '../api';
import {
  accountStateBadgeVariant,
  accountStateLabel,
  asAccountState,
  formatCooldown,
} from '../lib';

interface PoolHealthTableProps {
  health: PoolHealthResponse;
}

export const PoolHealthTable: React.FC<PoolHealthTableProps> = ({ health }) => {
  const accounts = health.accounts ?? [];

  return (
    <section className="fs-card fs-card--pad-sm" aria-labelledby="pool-health-heading">
      <div className="fs-page-head">
        <h2 id="pool-health-heading" className="fs-page-head__title">
          Pool connection status
          {health.degraded && (
            <span className="fs-badge fs-badge--danger admin-badge">Degraded</span>
          )}
        </h2>
      </div>

      <p className="fs-muted">
        {health.healthy}/{health.target} healthy · {health.cooling} cooling ·{' '}
        {health.quarantined} quarantined · {health.size} total
        {health.as_of && <> · as of {new Date(health.as_of).toLocaleString()}</>}
      </p>

      {health.stale && (
        <p role="status" className="fs-error" data-testid="pool-stale-banner">
          No fresh data from the collector — the snapshot is stale (the collector
          may be down or lagging). The per-account list is unavailable until it
          reports again.
        </p>
      )}

      {!health.stale && accounts.length === 0 ? (
        <p className="fs-muted">No pool accounts.</p>
      ) : (
        accounts.length > 0 && (
          <div className="fs-table-wrap">
            <table className="fs-table fs-table--hover">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">State</th>
                  <th scope="col">Cooldown</th>
                  <th scope="col">Last error</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => {
                  const state = asAccountState(account.state);
                  const cooldown = formatCooldown(account.cooldown_remaining_seconds);
                  return (
                    <tr key={account.index}>
                      <td>{account.index}</td>
                      <td>
                        <span
                          className={`fs-badge fs-badge--${accountStateBadgeVariant(state)}`}
                        >
                          {accountStateLabel(state)}
                        </span>
                      </td>
                      <td>{state === 'cooling' && cooldown ? cooldown : '—'}</td>
                      <td>
                        {state === 'quarantined' && account.last_error_reason
                          ? account.last_error_reason
                          : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      )}
    </section>
  );
};
