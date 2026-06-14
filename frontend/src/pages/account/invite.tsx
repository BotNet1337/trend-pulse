/**
 * InvitePage — /account/invite route (TASK-046).
 *
 * Shows the authenticated user's referral link and earned rewards list.
 * Calls GET /referral/me via useReferralMe hook (lazy code generation on first
 * call — backend creates the ref_code if not yet set).
 */

import * as React from 'react';

import { useReferralMe, type ReferralRewardItem } from '@/features/referral';
import { Button } from '@/shared/components/button';

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
  <tr>
    <td>#{reward.id}</td>
    <td className="fs-mono">${reward.amount_usdt.toFixed(2)}</td>
    <td>
      <span
        className={
          reward.status === 'paid'
            ? 'fs-badge fs-badge--success'
            : 'fs-badge fs-badge--warning'
        }
      >
        {statusLabel(reward.status)}
      </span>
    </td>
    <td>
      {reward.paid_at ? new Date(reward.paid_at).toLocaleDateString() : '—'}
    </td>
  </tr>
);

export const InvitePage: React.FC = () => {
  const { data, isLoading, isError } = useReferralMe();
  const [copied, setCopied] = React.useState(false);

  const handleCopy = () => {
    if (!data?.referral_link) return;
    void navigator.clipboard.writeText(data.referral_link).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <main className="fs-main">
      <div className="fs-container invite-wrap">
          <div className="fs-page-head">
            <div>
              <span className="invite-eyebrow">Referrals</span>
              <h1 className="fs-page-head__title">Invite a friend</h1>
              <p className="invite-intro">
                Share your invite link. When a friend makes their first payment, you earn{' '}
                <strong>$10 USDT</strong>.
              </p>
            </div>
          </div>

          {isLoading && (
            <div className="fs-center fs-muted" style={{ padding: '4rem 0' }}>
              Loading referral data…
            </div>
          )}

          {isError && (
            <div role="alert" className="fs-banner fs-banner--danger">
              Failed to load referral data. Please try again.
            </div>
          )}

          {data && (
            <>
              {/* Referral link section */}
              <section className="fs-card link-card" aria-label="Your invite link">
                <h2>Your invite link</h2>
                <div className="link-row">
                  <input
                    readOnly
                    value={data.referral_link}
                    className="fs-input"
                    aria-label="Referral link"
                  />
                  <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
                    {copied ? 'Copied!' : 'Copy'}
                  </Button>
                </div>
                <p className="link-code">
                  Your code: <code>{data.ref_code}</code>
                </p>
              </section>

              {/* Rewards section */}
              <section className="rewards-section" aria-labelledby="rewards-heading">
                <h2 id="rewards-heading">Earned rewards</h2>
                {data.rewards.length === 0 ? (
                  <p className="fs-muted">
                    No rewards yet. Share your link to start earning!
                  </p>
                ) : (
                  <div className="fs-table-wrap">
                    <table className="fs-table fs-table--hover">
                      <thead>
                        <tr>
                          <th scope="col">#</th>
                          <th scope="col">Amount</th>
                          <th scope="col">Status</th>
                          <th scope="col">Paid at</th>
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
  );
};
