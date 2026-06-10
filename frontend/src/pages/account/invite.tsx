/**
 * InvitePage — /account/invite route (TASK-046).
 *
 * Shows the authenticated user's referral link and earned rewards list.
 * Calls GET /referral/me via useReferralMe hook (lazy code generation on first
 * call — backend creates the ref_code if not yet set).
 */

import * as React from 'react';
import { useNavigate } from '@tanstack/react-router';

import { useLogout } from '@/features/auth';
import { useReferralMe, type ReferralRewardItem } from '@/features/referral';
import { Button } from '@/shared/components/button';
import { BRAND_NAME } from '@/shared/config';

/** Map reward status to a human-readable label. */
function statusLabel(status: string): string {
  switch (status) {
    case 'paid':
      return 'Paid';
    case 'pending':
      return 'Pending';
    default:
      return status;
  }
}

/** Single reward row in the table. */
const RewardRow: React.FC<{ reward: ReferralRewardItem }> = ({ reward }) => (
  <tr className="border-b border-border last:border-0">
    <td className="py-2 pr-4 text-sm text-muted-foreground">#{reward.id}</td>
    <td className="py-2 pr-4 text-sm font-mono">${reward.amount_usdt.toFixed(2)}</td>
    <td className="py-2 pr-4 text-sm">
      <span
        className={
          reward.status === 'paid'
            ? 'text-green-600 dark:text-green-400 font-medium'
            : 'text-amber-600 dark:text-amber-400 font-medium'
        }
      >
        {statusLabel(reward.status)}
      </span>
    </td>
    <td className="py-2 text-sm text-muted-foreground">
      {reward.paid_at ? new Date(reward.paid_at).toLocaleDateString() : '—'}
    </td>
  </tr>
);

export const InvitePage: React.FC = () => {
  const { data, isLoading, isError } = useReferralMe();
  const logoutMutation = useLogout();
  const navigate = useNavigate();
  const [copied, setCopied] = React.useState(false);

  const handleCopy = () => {
    if (!data?.referral_link) return;
    void navigator.clipboard.writeText(data.referral_link).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="auth-light h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <header className="border-b border-border px-8 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void navigate({ to: '/account/settings' })}
          aria-label="Account settings"
        >
          Settings
        </Button>
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

      <main className="flex-1 min-w-0 bg-background overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[640px] flex-col gap-8 px-8 py-8">
          <header className="flex flex-col gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-medium">
              Referrals
            </span>
            <h1 className="m-0 text-2xl font-bold tracking-[-0.01em]">Invite a friend</h1>
            <p className="m-0 text-sm text-muted-foreground">
              Share your invite link. When a friend makes their first payment, you earn{' '}
              <span className="font-semibold text-foreground">$10 USDT</span>.
            </p>
          </header>

          {isLoading && (
            <div className="flex items-center justify-center py-16 text-muted-foreground text-sm">
              Loading referral data…
            </div>
          )}

          {isError && (
            <div
              role="alert"
              className="rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
            >
              Failed to load referral data. Please try again.
            </div>
          )}

          {data && (
            <>
              {/* Referral link section */}
              <section className="flex flex-col gap-3 rounded-xl border border-border p-5">
                <h2 className="text-sm font-semibold">Your invite link</h2>
                <div className="flex items-center gap-2">
                  <input
                    readOnly
                    value={data.referral_link}
                    className="flex-1 rounded-lg border border-border bg-muted px-3 py-2 text-sm font-mono text-foreground"
                    aria-label="Referral link"
                  />
                  <Button type="button" size="sm" onClick={handleCopy}>
                    {copied ? 'Copied!' : 'Copy'}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Your code:{' '}
                  <span className="font-mono font-medium text-foreground">{data.ref_code}</span>
                </p>
              </section>

              {/* Rewards section */}
              <section className="flex flex-col gap-3">
                <h2 className="text-sm font-semibold">Earned rewards</h2>
                {data.rewards.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No rewards yet. Share your link to start earning!
                  </p>
                ) : (
                  <div className="rounded-xl border border-border overflow-hidden">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b border-border bg-muted/50">
                          <th className="py-2 pr-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-[0.05em]">
                            #
                          </th>
                          <th className="py-2 pr-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-[0.05em]">
                            Amount
                          </th>
                          <th className="py-2 pr-4 text-left text-xs font-medium text-muted-foreground uppercase tracking-[0.05em]">
                            Status
                          </th>
                          <th className="py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-[0.05em]">
                            Paid at
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.rewards.map((reward) => (
                          <RewardRow key={reward.id} reward={reward} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
};
