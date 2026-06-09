/**
 * PacksBlock — «Наборы» widget for the watchlists page.
 *
 * Shows the curated pack catalog with subscribe/unsubscribe buttons.
 * Handles:
 *   - Loading state
 *   - 402 → human-readable plan limit message
 *   - Subscribe / Unsubscribe with created/skipped feedback
 */

import React, { useState } from 'react';
import { usePacks, useSubscribePack, useUnsubscribePack } from './queries';
import type { PackRead } from './api';
import { extractErrorMessage } from './error-message';
import { Button } from '@/shared/components/button';

interface PackRowProps {
  pack: PackRead;
}

const PackRow: React.FC<PackRowProps> = ({ pack }) => {
  const subscribeMutation = useSubscribePack();
  const unsubscribeMutation = useUnsubscribePack();
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubscribe = async () => {
    setFeedback(null);
    setError(null);
    try {
      const result = await subscribeMutation.mutateAsync(pack.slug);
      if (result.created === 0) {
        setFeedback(`Уже подключён (${result.skipped} каналов пропущено)`);
      } else {
        setFeedback(
          `Подключён: ${result.created} канала добавлено${result.skipped > 0 ? `, ${result.skipped} уже было` : ''}`,
        );
      }
    } catch (err: unknown) {
      setError(extractErrorMessage(err));
    }
  };

  const handleUnsubscribe = async () => {
    setFeedback(null);
    setError(null);
    try {
      const result = await unsubscribeMutation.mutateAsync(pack.slug);
      setFeedback(`Отключён: удалено ${result.deleted} каналов`);
    } catch (err: unknown) {
      setError(extractErrorMessage(err));
    }
  };

  const isPending = subscribeMutation.isPending || unsubscribeMutation.isPending;

  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold text-sm">{pack.title}</span>
          <span className="text-xs text-muted-foreground">
            {pack.topic} &middot; {pack.channels_count} каналов
          </span>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isPending}
            onClick={() => void handleSubscribe()}
            aria-label={`Подключить набор ${pack.title}`}
          >
            {subscribeMutation.isPending ? 'Подключение…' : 'Подключить'}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={isPending}
            onClick={() => void handleUnsubscribe()}
            aria-label={`Отключить набор ${pack.title}`}
          >
            {unsubscribeMutation.isPending ? 'Отключение…' : 'Отключить'}
          </Button>
        </div>
      </div>
      {feedback && (
        <p className="text-xs text-muted-foreground mt-1" aria-live="polite">
          {feedback}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive mt-1">
          {error}
        </p>
      )}
    </li>
  );
};

/** «Наборы» block — rendered on the watchlists list page. */
export const PacksBlock: React.FC = () => {
  const { data: packs, isLoading, error } = usePacks();

  return (
    <section aria-labelledby="packs-heading" className="mt-10">
      <h2 id="packs-heading" className="text-xl font-bold mb-4">
        Наборы каналов
      </h2>
      <p className="text-sm text-muted-foreground mb-4">
        Готовые подборки каналов — подключайте в один клик. Не считаются в лимит ваших каналов.
      </p>

      {isLoading && (
        <div aria-busy="true" aria-label="Загрузка наборов" className="py-8 flex justify-center">
          <span className="text-sm text-muted-foreground">Загрузка…</span>
        </div>
      )}

      {!isLoading && error && (
        <p role="alert" className="text-sm text-destructive">
          Не удалось загрузить наборы. Попробуйте обновить страницу.
        </p>
      )}

      {!isLoading && !error && packs && packs.length === 0 && (
        <p className="text-sm text-muted-foreground">Каталог наборов пуст.</p>
      )}

      {!isLoading && !error && packs && packs.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="Каталог наборов">
          {packs.map((pack) => (
            <PackRow key={pack.slug} pack={pack} />
          ))}
        </ul>
      )}
    </section>
  );
};
