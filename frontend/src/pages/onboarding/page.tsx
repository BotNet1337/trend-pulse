/**
 * OnboardingPage — /onboarding (TASK-039)
 *
 * Flow: pick a pack → see live trending data → CTA «Connect pack» subscribes
 * → navigate to /watchlists.
 *
 * Decision (task doc §Discussion):
 *  - Accessible directly (no redirect if user already has watchlists).
 *  - Redirect INTO /onboarding happens in AuthGuard/index route (0 watchlists criterion).
 *  - Not a plan-gated page — Free users land here after first login.
 */

import React, { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { usePacks, useSubscribePack } from '@/features/packs';
import { useTrending, TrendingList } from '@/features/trending';
import { Button } from '@/shared/components/button';
import { paths } from '@/app/router/path';

export const OnboardingPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: packs, isLoading: packsLoading } = usePacks();
  const subscribeMutation = useSubscribePack();

  // Selected pack slug — default to first available pack when catalog loads
  const [selectedSlug, setSelectedSlug] = useState<string>('');

  // Derive effective slug — prefer user selection, fall back to first catalog entry
  const effectiveSlug =
    selectedSlug || (packs && packs.length > 0 ? packs[0].slug : '');

  const { data: trending, isLoading: trendingLoading, isError: trendingError } =
    useTrending(effectiveSlug);

  const [subscribeError, setSubscribeError] = useState<string | null>(null);
  const [subscribed, setSubscribed] = useState(false);

  const handleSubscribe = async () => {
    if (!effectiveSlug) return;
    setSubscribeError(null);
    try {
      await subscribeMutation.mutateAsync(effectiveSlug);
      setSubscribed(true);
      void navigate({ to: paths.watchlists.list, replace: true });
    } catch (err: unknown) {
      const e = err as {
        response?: { status?: number; data?: { error?: { message?: string }; detail?: string } };
      };
      // Read envelope message first (TASK-030 unified format), fall back to legacy {detail}.
      const detail = e.response?.data?.error?.message ?? e.response?.data?.detail;
      setSubscribeError(
        detail ? `Error: ${detail}` : 'Failed to connect the pack. Please try again.',
      );
    }
  };

  const selectedPack = packs?.find((p) => p.slug === effectiveSlug);

  return (
    <main className="fs-main">
      <div className="fs-container ob-container">
        {/* Step header */}
        <div className="fs-page-head">
          <h1 className="fs-page-head__title">Welcome!</h1>
          <p className="fs-page-head__sub">
            Pick a topic — and see what went viral in the last 24 hours.
          </p>
        </div>

        {/* Pack selector */}
        <section aria-labelledby="pack-selector-heading">
          <h2 id="pack-selector-heading" className="ob-step-title">
            Step 1 — Pick a pack
          </h2>

          {packsLoading && <p className="fs-muted">Loading packs…</p>}

          {!packsLoading && packs && (
            <div className="fs-segment pack-segment" role="group" aria-label="Pack selection">
              {packs.map((pack) => {
                const isActive = pack.slug === effectiveSlug;
                return (
                  <button
                    key={pack.slug}
                    type="button"
                    onClick={() => setSelectedSlug(pack.slug)}
                    aria-pressed={isActive}
                  >
                    {pack.title}
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {/* Trending preview */}
        {effectiveSlug && (
          <section aria-labelledby="trending-heading" className="fs-section">
            <h2 id="trending-heading" className="ob-step-title">
              Step 2 — Viral in the last 24 hours
              {selectedPack && (
                <span className="ob-step-note"> · {selectedPack.title}</span>
              )}
            </h2>

            <TrendingList
              items={trending?.items ?? []}
              isLoading={trendingLoading}
              isError={trendingError}
              warmingUp={trending?.warming_up ?? false}
            />
          </section>
        )}

        {/* CTA */}
        <section aria-labelledby="cta-heading" className="fs-section">
          <h2 id="cta-heading" className="ob-step-title">
            Step 3 — Connect a pack
          </h2>
          <p className="fs-muted" style={{ fontSize: '0.9rem', maxWidth: '60ch', marginBottom: '1rem' }}>
            Connect a pack to get personal signals when its topics start spreading virally
            on Telegram.
          </p>

          {subscribeError && (
            <p role="alert" className="fs-error" style={{ marginBottom: '0.75rem' }}>
              {subscribeError}
            </p>
          )}

          <div className="fs-row">
            <Button
              type="button"
              disabled={!effectiveSlug || subscribeMutation.isPending || subscribed}
              onClick={() => void handleSubscribe()}
              aria-label={
                effectiveSlug
                  ? `Connect pack ${selectedPack?.title ?? effectiveSlug}`
                  : 'Pick a pack'
              }
            >
              {subscribeMutation.isPending
                ? 'Connecting…'
                : subscribed
                  ? 'Connected!'
                  : 'Connect pack'}
            </Button>

            <Button
              type="button"
              variant="ghost"
              onClick={() => void navigate({ to: paths.watchlists.list })}
            >
              Skip
            </Button>
          </div>
        </section>
      </div>
    </main>
  );
};
