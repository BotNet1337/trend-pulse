# Product State 02 — Целевое состояние продукта (TO-BE)

> Куда ведём продукт, чтобы скоринг стал **ядром ценности и моатом**. Подкреплено research-ом
> ([`../../research/scoring-target-research.md`](../../research/scoring-target-research.md)) и архитектурным target
> ([`../../architecture/states/02-state-target.md`](../../architecture/states/02-state-target.md)). Решения — с вариантами (≥5).

Status: **target proposal** · pre-revenue, рамка «conditional growth», не «predict virality from scratch».

---

## 1. Целевое value-обещание (точная формулировка)

AS-IS питч: «детектор вирусного контента». Проблема: (а) over-claim (предсказать вирусность с нуля
невозможно, Martin&Watts <50% дисперсии); (б) сигнал голодает → пользователь видит «×0.0».

**TO-BE обещание (research-дефендебл):**

> **«Foresignal ловит историю в момент, когда она перепрыгивает с канала на канал — и говорит,
> насколько независимо (а не накручено) она разгоняется, раньше мейнстрима.»**

Три проверяемых столпа, каждый = видимый элемент UI:
1. **Cross-channel breadth** — «история уже в N независимых каналах» (Weng 2013: широта > объём).
2. **Calibrated `p(grow)`** — «вероятность что продолжит разгоняться» (Cheng 2014: 0.795/0.877).
3. **Source-independence** — «органика vs накрутка» бейдж (Ugander 2012 / CIB).

## 2. Моат, сделанный конкретным

| Слой моата | AS-IS | TO-BE |
|---|---|---|
| Cross-channel story clustering | per-batch, ~12% multi-channel | loose cross-channel merge, ≥35% multi-channel |
| Independence сигнал | нет | eff-independent-sources фича + anti-collusion бейдж |
| Калиброванная вероятность | нет (0–100 формула) | `p(grow)` GBDT, Brier ≤0.12 |
| Скорость | ~6 мин | <2 мин (event-driven) |
| Экономика (cross-tenant dedup) | есть | сохраняется (стоимость ~ числу постов) |

Никто из конкурентов (§4) не делает **пересечение** этих слоёв — это и есть defensible whitespace.

## 3. Целевые KPI продукта

| KPI | AS-IS | Target |
|---|---|---|
| Истинные алерты/неделя (≥порог, 👍) | ~0 | стабильный поток |
| Alert precision (👍/👍+👎) | n/a | ≥0.6 |
| Latency post→alert p50 | ~6 мин | <2 мин |
| «Aha» за сессию (увидел реальный кросс-канальный сигнал) | редко | каждый онбординг |
| Конверсия Free→Pro | n/a | измеримая после потока алертов |
| Первый платящий → $2k MRR | 0 | по плану 6 мес |

## 4. Конкурентное позиционирование (TO-BE)

| Конкурент | Чем берёт | Чего НЕ делает (наш зазор) |
|---|---|---|
| **TGStat/Telemetr** | глубина RU-TG данных, citation index | нет per-story clustering, нет independence, нет персональных алертов |
| **Santiment** (ближайший) | TG ingest (6000+), Trending Stories (20-мин word-spike), on-chain | word-level, не near-dup story; нет productized independence-weighted score; не crypto-RU-native |
| **LunarCrush** | Galaxy Score, share-of-voice | TG только output; influence-weighted, не cross-channel breadth |
| **Brand24/Brandwatch** | enterprise listening | дорого, не TG-native, нет virality-score истории |
| **Cornix/aggregators** | консолидируют call-каналы | copy/execute, не вирусность/независимость |

**Позиция:** «Santiment для одного трейдера, но на уровне *историй* и с честным сигналом независимости,
быстрее и в crypto-RU Telegram». Бенчмаркимся против Santiment Trending Stories.

## 5. Узловые продуктовые решения (≥5 вариантов)

### P1. Что показывать как главный «Live signal» в `/watchlists`

1. **(Рек.) `p(grow)` 0–100% + breadth-бейдж «N каналов» + independence-бейдж + sparkline.**
2. Только viral_score 0–100 (минимальный диффект, S1).
3. Тройной бейдж score/breadth/independence без вероятности.
4. «Светофор» (🟢 разгоняется / 🟡 / ⚪) поверх p(grow) — проще для трейдера.
5. Лента «истории на подъёме» (ранжир по p_grow), не per-channel строки.
6. Гибрид: per-channel строка + раскрытие в story-view с независимостью.

→ Поэтапно: **2 (быстро, уже посчитано) → 1 (после GBDT) → 5/6 (story-centric)**.

### P2. Монетизация улучшенного сигнала

1. **(Рек.) Independence/anti-collusion бейдж + `p(grow)` — Pro-фича** (Free видит score, Pro — вероятность+независимость).
2. Story-view с графом независимости — Trader-фича.
3. Latency-тиры (Free 30-мин, Pro real-time, Trader <2 мин).
4. API доступ к p(grow)/independence — Trader/B2B.
5. «Confidence-only» алерты (Pro фильтрует по p_grow≥X).
6. Backtesting исторических сигналов как платная фича.

→ **1+3 ядро; 2/4 — апсейл Trader.**

### P3. Онбординг под новый сигнал

1. **(Рек.) Curated overlapping packs**, гарантирующие cross-channel событие в первый день → «aha».
2. Демо-режим на исторических кросс-канальных кейсах.
3. Гайд «почему N каналов = сигнал, а 1 канал = шум».
4. Сравнение с мейнстримом («мы дали на 23 мин раньше»).
5. Sample-алерт сразу после регистрации.
6. Showcase-канал как live-proof перед оплатой.

→ **1+4+6.**

## 6. Риски продукта

- **Over-promise независимости** — не позиционировать как «детектор ботов»; рамка «сигнал независимости», парится с synchrony.
- **Пустой опыт** — без широты (D7 в arch) онбординг не даёт «aha»; ingest-объём — пререквизит.
- **Higgs≠TG** — не публиковать «0.92 AUC» как продуктовое обещание до shadow-eval на TG.
- **Дистрибуция** — узкое место остаётся; сигнал-улучшение усиливает showcase-proof, но не заменяет дистрибуцию.

## 7. Что должно быть правдой, чтобы выиграть (acceptance)

1. Поток истинных кросс-канальных алертов (≥35% multi-channel кластеров).
2. `p(grow)` калиброван и измеряется онлайн (shadow PR-AUC ≥0.80@1ч, Brier ≤0.12).
3. UI показывает p_grow + breadth + independence, а не velocity.
4. Latency p50 < 2 мин.
5. Showcase даёт публичный proof-of-speed на реальном событии.

→ Реализация — [`../../architecture/states/03-scoring-evolution-plan.md`](../../architecture/states/03-scoring-evolution-plan.md).
</content>
