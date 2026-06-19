/**
 * PoolHealthTable (TASK-117) — per-account pool connection-status table.
 *
 * One row per account, identified by its @username (`display_label`, falling back to
 * `#<index>` for env/legacy slots) with the numeric index as a muted secondary detail; a
 * state badge (Connected/Cooling/Quarantined/Failing); a cooldown for cooling accounts;
 * and the last-error reason — shown for EVERY account that has one (not only quarantined),
 * with a human RU explanation + the cumulative failure count, so the owner can react to
 * recurring session errors (e.g. the "wrong session ID" conflict). A "stale" banner shows
 * when the collector snapshot is missing/old.
 *
 * Styling mirrors the admin-metrics dashboard (`fs-*` / `fs-table` classes).
 */

import React from 'react';
import type { PoolHealthResponse } from '../api';
import {
  accountErrorExplanation,
  accountLabel,
  accountSourceBadgeVariant,
  accountSourceLabel,
  accountStateBadgeVariant,
  accountStateLabel,
  asAccountSource,
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
        {health.healthy} healthy · {health.cooling} cooling · {health.quarantined} quarantined ·{' '}
        {health.size} total · target {health.target}
        {health.as_of && <> · as of {new Date(health.as_of).toLocaleString()}</>}
      </p>

      {health.ingest_contradiction && (
        <p role="alert" className="fs-error" data-testid="pool-ingest-contradiction-banner">
          All accounts report healthy, but no posts are being ingested — the pool looks
          green yet ingest is stale. An account may be connected but failing every read
          (see the per-account state below).
        </p>
      )}

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
                  <th scope="col">Account</th>
                  <th scope="col">Source</th>
                  <th scope="col">State</th>
                  <th scope="col">Cooldown</th>
                  <th scope="col">Last error</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => {
                  const state = asAccountState(account.state);
                  const source = asAccountSource(account.source);
                  const cooldown = formatCooldown(account.cooldown_remaining_seconds);
                  // Surface the recorded error for EVERY account that has one (not only
                  // quarantined/failing) — a healthy-but-intermittently-erroring session
                  // (the "wrong session ID" case) must still be visible to the owner.
                  const errorReason = account.last_error_reason?.trim()
                    ? account.last_error_reason.trim()
                    : null;
                  const explanation = accountErrorExplanation(errorReason);
                  const failureCount = account.read_failure_count ?? 0;
                  // Show the muted `#index` secondary detail only when the row already has a
                  // @username headline — for an env/legacy slot the headline IS `#index`, so
                  // repeating it would be redundant.
                  const hasUsername = Boolean(account.display_label?.trim());
                  return (
                    <tr key={account.index}>
                      <td>
                        <span className="font-mono" data-testid="pool-account-label">
                          {accountLabel(account.display_label, account.index)}
                        </span>
                        {hasUsername && (
                          <>
                            {' '}
                            <span className="fs-muted" data-testid="pool-account-index">
                              #{account.index}
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        <span
                          className={`fs-badge fs-badge--${accountSourceBadgeVariant(source)}`}
                          data-testid="pool-account-source"
                        >
                          {accountSourceLabel(source)}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`fs-badge fs-badge--${accountStateBadgeVariant(state)}`}
                        >
                          {accountStateLabel(state)}
                        </span>
                      </td>
                      <td>{state === 'cooling' && cooldown ? cooldown : '—'}</td>
                      <td>
                        {explanation ? (
                          <span
                            className="fs-badge fs-badge--warning"
                            data-testid="pool-account-error"
                            title={errorReason ?? undefined}
                          >
                            ⚠ {explanation}
                            {failureCount > 0 ? ` ×${failureCount}` : ''}
                          </span>
                        ) : (
                          '—'
                        )}
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
