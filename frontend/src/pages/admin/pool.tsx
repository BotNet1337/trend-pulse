/**
 * AdminPoolPage — /admin/pool (TASK-117, TASK-136, superuser only).
 *
 * TG pool admin: a connection-status dashboard (per-account state + disconnect
 * reason, over GET /pool-admin/pool-health) plus an "Add account" QR-login flow
 * (start → QR → poll → reveal session string), plus the account-factory panel
 * (factory accounts list + budget summary + "Register account" trigger button).
 *
 * Access UX mirrors /admin/metrics: a regular authenticated user sees the SAME
 * markup as a real 404 (no existence leak); the request is not sent for
 * non-superusers, and a racy 403 also collapses into the not-found state. The
 * real protection is `current_superuser` on the server route — this is UX only.
 */

import React from 'react';
import { useCurrentUser } from '@/entities/viewer/model';
import {
  FactoryAccountsPanel,
  PoolHealthTable,
  QrLoginDialog,
  factoryRegisterDisabledTooltip,
  isFactoryRegisterDisabled,
  shouldShowPoolAdminNotFound,
  useFactoryAccounts,
  useFactoryBudget,
  usePoolHealth,
  useTriggerFactory,
} from '@/features/pool-admin';
import { Button } from '@/shared/components/button';
import { RefreshCw } from '@/shared/images';
import { NotFoundPage } from '@/pages/error';

export const AdminPoolPage: React.FC = () => {
  const { data: user, isLoading: isUserLoading } = useCurrentUser();
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const isSuperuser = user?.is_superuser === true;
  const {
    data: health,
    isLoading: isHealthLoading,
    isFetching,
    error,
    refetch,
  } = usePoolHealth(isSuperuser);

  const { data: factoryBudget } = useFactoryBudget(isSuperuser);
  const { data: factoryAccounts } = useFactoryAccounts(isSuperuser);
  const triggerFactory = useTriggerFactory();

  const errorStatus = (error as { response?: { status?: number } } | null)?.response
    ?.status;
  const triggerStatus = (
    triggerFactory.error as { response?: { status?: number } } | null
  )?.response?.status;

  if (shouldShowPoolAdminNotFound(user, errorStatus)) {
    return <NotFoundPage />;
  }

  const isLoading = isUserLoading || (isSuperuser && isHealthLoading);
  const isUnconfigured = errorStatus === 503;

  const registerDisabled =
    !isSuperuser || isFactoryRegisterDisabled(factoryBudget) || triggerFactory.isPending;
  const registerTooltip = factoryBudget && !factoryBudget.enabled
    ? factoryRegisterDisabledTooltip()
    : undefined;

  return (
    <main className="fs-main">
      <div className="fs-container">
        <div className="fs-page-head">
          <h1 className="fs-page-head__title">
            TG pool
            <span className="fs-badge fs-badge--info admin-badge">Admin</span>
          </h1>
          <div className="fs-page-head__actions" style={{ display: 'flex', gap: '0.5rem' }}>
            <Button
              type="button"
              variant="outline"
              onClick={() => void refetch()}
              disabled={!isSuperuser || isFetching}
            >
              <RefreshCw className="mr-1.5 h-4 w-4" />
              {isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
            <Button type="button" onClick={() => setDialogOpen(true)} disabled={!isSuperuser}>
              Add / re-connect account
            </Button>
            <Button
              type="button"
              data-testid="factory-register-button"
              disabled={registerDisabled}
              title={registerTooltip}
              // `mutate` (not `mutateAsync`) so a rejected request lands in the mutation's
              // error state below instead of becoming an unhandled promise rejection.
              onClick={() => triggerFactory.mutate(undefined)}
            >
              {triggerFactory.isPending ? 'Registering…' : 'Register account'}
            </Button>
          </div>
        </div>

        {isLoading && (
          <div
            aria-busy="true"
            aria-label="Loading pool health"
            className="fs-center"
            style={{ padding: '4rem 0' }}
          >
            <span className="fs-muted">Loading…</span>
          </div>
        )}

        {!isLoading && error && errorStatus !== 403 && (
          <p role="alert" className="fs-error">
            {isUnconfigured
              ? 'Pool-health is unavailable (the health store is unreachable).'
              : 'Failed to load pool health. Please refresh.'}
          </p>
        )}

        {!isLoading && health && <PoolHealthTable health={health} />}

        {triggerFactory.isError && (
          <p role="alert" className="fs-error" data-testid="factory-register-error">
            {triggerStatus === 503
              ? 'Account factory is disabled (no provider configured).'
              : 'Failed to trigger the account factory. Please try again.'}
          </p>
        )}

        {isSuperuser && factoryBudget && (
          <FactoryAccountsPanel
            accounts={factoryAccounts ?? []}
            budget={factoryBudget}
          />
        )}
      </div>

      <QrLoginDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </main>
  );
};
