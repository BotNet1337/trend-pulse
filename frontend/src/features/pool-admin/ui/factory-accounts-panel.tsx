/**
 * FactoryAccountsPanel (TASK-136) — factory account lifecycle table + budget summary.
 *
 * Presentational: data fetching stays in the page (same as PoolHealthTable taking `health`
 * as a prop). Renders one row per factory account with state badge, probation countdown,
 * cost, and last_error; plus a budget summary line at the top.
 *
 * Styling mirrors pool-health-table.tsx (`fs-card`, `fs-table` classes).
 */

import React from 'react';
import type { FactoryAccount, FactoryBudget } from '../api';
import {
  asFactoryAccountState,
  factoryStateBadgeVariant,
  factoryStateLabel,
  formatProbationCountdown,
} from '../lib';

interface FactoryAccountsPanelProps {
  accounts: FactoryAccount[];
  budget: FactoryBudget;
}

export const FactoryAccountsPanel: React.FC<FactoryAccountsPanelProps> = ({
  accounts,
  budget,
}) => {
  return (
    <section className="fs-card fs-card--pad-sm" aria-labelledby="factory-accounts-heading">
      <div className="fs-page-head">
        <h2
          id="factory-accounts-heading"
          className="fs-page-head__title"
          data-testid="factory-accounts-heading"
        >
          Account factory
          {!budget.enabled && (
            <span className="fs-badge fs-badge--neutral admin-badge">disabled</span>
          )}
        </h2>
      </div>

      <p className="fs-muted">
        Provider: {budget.provider || '(none)'} · ${budget.remaining_usd} remaining / $
        {budget.budget_usd} budget · spent ${budget.spent_usd}
        {!budget.enabled && (
          <> · <span className="fs-error">factory disabled — no provider configured</span></>
        )}
      </p>

      {accounts.length === 0 ? (
        <p className="fs-muted" data-testid="factory-accounts-empty">
          No factory accounts.
        </p>
      ) : (
        <div className="fs-table-wrap">
          <table className="fs-table fs-table--hover">
            <thead>
              <tr>
                <th scope="col">Phone</th>
                <th scope="col">State</th>
                <th scope="col">Probation</th>
                <th scope="col">Cost</th>
                <th scope="col">Last error</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => {
                const state = asFactoryAccountState(account.state);
                const probationCountdown = formatProbationCountdown(account.probation_until);
                return (
                  <tr key={account.id}>
                    <td>
                      <span className="font-mono">{account.phone_masked}</span>
                    </td>
                    <td>
                      <span
                        className={`fs-badge fs-badge--${factoryStateBadgeVariant(state)}`}
                        data-testid="factory-account-state"
                      >
                        {factoryStateLabel(state)}
                      </span>
                    </td>
                    <td>
                      {probationCountdown ? (
                        <span className="fs-muted" data-testid="factory-account-probation">
                          {probationCountdown}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>${account.cost_usd}</td>
                    <td>
                      {account.last_error ? (
                        <span
                          className="fs-badge fs-badge--warning"
                          data-testid="factory-account-error"
                          title={account.last_error}
                        >
                          ⚠ {account.last_error}
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
      )}
    </section>
  );
};
