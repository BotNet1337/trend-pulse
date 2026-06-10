/**
 * TrendingList — renders viral clusters from GET /trending.
 *
 * States:
 *  - loading   → spinner placeholder
 *  - error     → user-friendly error message
 *  - warming_up → "собираем сигналы…" placeholder (showcase not yet warmed)
 *  - empty     → honest empty state (no 24h activity for this pack)
 *  - items     → ranked list of trending topics with viral_score + first_seen
 */

import React from 'react';
import type { TrendingItem } from './api';

interface TrendingListProps {
  items: TrendingItem[];
  isLoading: boolean;
  isError: boolean;
  warmingUp: boolean;
}

function formatScore(score: number): string {
  return score.toFixed(1);
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

const TrendingItemRow: React.FC<{ item: TrendingItem; rank: number }> = ({ item, rank }) => (
  <li className="flex items-start gap-3 p-3 rounded-lg border border-border bg-card">
    <span className="text-muted-foreground text-sm font-mono w-5 shrink-0">{rank}.</span>
    <div className="flex-1 min-w-0">
      <p className="font-semibold text-sm truncate">{item.topic}</p>
      <p className="text-xs text-muted-foreground mt-0.5">
        Вирусность: {formatScore(item.viral_score)} &middot;{' '}
        {formatDate(item.first_seen as unknown as string)}
      </p>
    </div>
  </li>
);

export const TrendingList: React.FC<TrendingListProps> = ({
  items,
  isLoading,
  isError,
  warmingUp,
}) => {
  if (isLoading) {
    return (
      <div aria-busy="true" aria-label="Загрузка трендов" className="py-6 flex justify-center">
        <span className="text-sm text-muted-foreground">Загрузка…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive py-4">
        Не удалось загрузить тренды. Попробуйте обновить страницу.
      </p>
    );
  }

  if (warmingUp) {
    return (
      <div
        className="py-6 flex flex-col items-center gap-2 text-center"
        aria-label="Собираем данные"
      >
        <span className="text-2xl">📡</span>
        <p className="text-sm font-medium">Собираем сигналы…</p>
        <p className="text-xs text-muted-foreground">
          Showcase только что запустился. Данные появятся в течение нескольких минут.
        </p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        За последние 24 часа активности по этому набору не обнаружено.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" aria-label="Вирусные темы за 24 часа">
      {items.map((item, idx) => (
        <TrendingItemRow key={`${item.topic}-${idx}`} item={item} rank={idx + 1} />
      ))}
    </ul>
  );
};
