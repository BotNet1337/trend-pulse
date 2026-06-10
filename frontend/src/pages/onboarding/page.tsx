/**
 * OnboardingPage — /onboarding (TASK-039)
 *
 * Flow: pick a pack → see live trending data → CTA «Подключить набор» subscribes
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
import { BRAND_NAME } from '@/shared/config';
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
      const e = err as { response?: { status?: number; data?: { detail?: string } } };
      const detail = e.response?.data?.detail;
      setSubscribeError(
        detail ? `Ошибка: ${detail}` : 'Не удалось подключить набор. Попробуйте ещё раз.',
      );
    }
  };

  const selectedPack = packs?.find((p) => p.slug === effectiveSlug);

  return (
    <div className="min-h-dvh flex flex-col bg-background text-foreground auth-light">
      <header className="border-b border-border px-6 py-3 flex items-center">
        <span className="font-semibold text-sm">{BRAND_NAME}</span>
      </header>

      <main className="flex-1 container max-w-2xl mx-auto px-4 py-10">
        {/* Step header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold">Добро пожаловать!</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Выберите тему — и увидите, что завирусилось за последние 24 часа.
          </p>
        </div>

        {/* Pack selector */}
        <section aria-labelledby="pack-selector-heading" className="mb-6">
          <h2 id="pack-selector-heading" className="text-sm font-semibold mb-2 uppercase tracking-wide text-muted-foreground">
            Шаг 1 — Выберите набор
          </h2>

          {packsLoading && (
            <p className="text-sm text-muted-foreground">Загрузка наборов…</p>
          )}

          {!packsLoading && packs && (
            <div className="flex flex-wrap gap-2" role="group" aria-label="Выбор пака">
              {packs.map((pack) => {
                const isActive = pack.slug === effectiveSlug;
                return (
                  <button
                    key={pack.slug}
                    type="button"
                    onClick={() => setSelectedSlug(pack.slug)}
                    aria-pressed={isActive}
                    className={[
                      'px-4 py-2 rounded-full border text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background border-border text-foreground hover:bg-muted',
                    ].join(' ')}
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
          <section aria-labelledby="trending-heading" className="mb-8">
            <h2 id="trending-heading" className="text-sm font-semibold mb-3 uppercase tracking-wide text-muted-foreground">
              Шаг 2 — Вирусное за 24 часа
              {selectedPack && (
                <span className="normal-case ml-1 font-normal">
                  · {selectedPack.title}
                </span>
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
        <section aria-labelledby="cta-heading">
          <h2 id="cta-heading" className="text-sm font-semibold mb-3 uppercase tracking-wide text-muted-foreground">
            Шаг 3 — Подключите набор
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Подключите набор, чтобы получать персональные сигналы, когда темы из него начнут
            вирусно распространяться в Telegram.
          </p>

          {subscribeError && (
            <p role="alert" className="text-sm text-destructive mb-3">
              {subscribeError}
            </p>
          )}

          <div className="flex gap-3 flex-wrap">
            <Button
              type="button"
              disabled={!effectiveSlug || subscribeMutation.isPending || subscribed}
              onClick={() => void handleSubscribe()}
              aria-label={
                effectiveSlug
                  ? `Подключить набор ${selectedPack?.title ?? effectiveSlug}`
                  : 'Выберите набор'
              }
            >
              {subscribeMutation.isPending
                ? 'Подключение…'
                : subscribed
                  ? 'Подключено!'
                  : 'Подключить набор'}
            </Button>

            <Button
              type="button"
              variant="ghost"
              onClick={() => void navigate({ to: paths.watchlists.list })}
            >
              Пропустить
            </Button>
          </div>
        </section>
      </main>
    </div>
  );
};
