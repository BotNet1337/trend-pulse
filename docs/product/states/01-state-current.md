# Product State 01 — Текущее состояние продукта (AS-IS)

> Снимок продукта на 2026-06-16. Публичный бренд — **Foresignal** (landing https://foresignal.biz,
> SPA https://app.foresignal.biz), кодовое имя — **TrendPulse**. Источники: [`../overview.md`](../overview.md),
> [`../unit-economics.md`](../unit-economics.md), [`../epics/`](../epics/README.md), [`../../architecture/roadmap.md`](../../architecture/roadmap.md),
> [`cache/trendpulse-signal-quality-report.md`](../../../../../cache/trendpulse-signal-quality-report.md), [`cache/MANUAL-TODO.md`](../../../../../cache/MANUAL-TODO.md).
> Парный target — [`02-state-target.md`](./02-state-target.md).

Status: **pre-revenue / pre-first-paying-customer** — система построена и задеплоена, сигнал доказан на
малой выборке; между «построено» и «первый доллар» стоит owner-gated операционный чеклист (пул ≥3,
живой NOWPayments-платёж, первый showcase-пост) — то есть **дистрибуция и ops, не код**.

---

## 1. Что это и для кого

Персональный детектор вирусного контента из Telegram: пользователь даёт watchlist публичных каналов +
топик, система в реальном времени читает их через пул техаккаунтов (MTProto), кластеризует похожие
новости across каналов, считает viral score и шлёт алерт — `🔥 Viral alert [crypto] — "Bitcoin ETF
approval" Score 94 · 47 каналов за 23 мин`. **Ядро обещания — скорость: сигнал раньше мейнстрима**
(KPI post→alert — «тот самый, который продаём»). **Клин:** crypto-трейдеры, Telegram-native, crypto-RU.

## 2. Моат (как сформулирован в доках)

Два столпа: **кросс-канальная вирусность** и **независимость источников (noise-vs-independence)**.
viral_score строится на кросс-канальном распространении, не на single-channel популярности. Сигнал-quality
программа сделала это операционным: матчинг кластер→топик по пересечению каналов (не по строке), velocity
переопределён как `log1p(Δchannels−1)/Δhrs` → «single-channel ≠ viral». Экономический столп моата —
**cross-tenant dedup каналов**: канал читается один раз даже если его смотрят 100 юзеров → «стоимость
растёт от числа постов, не от числа юзеров».

## 3. Цены и планы (TASK-049, 2026-06-11)

| | Free (воронка) | Pro | Trader (`team`) |
|---|---|---|---|
| $/мес | $0 | **$29** | **$99** |
| Свои каналы | 0 | 100 | 500 |
| Топики | 1 | 5 | unlimited |
| Алерты/день | 5 (30-мин задержка) | unlimited | unlimited |
| История | — | 30 дней | 90 дней |
| Webhook / API | — / — | ✓ / — | ✓ / ✓ |

Free — **воронка** (curated packs + 30-мин задержка, 0 своих каналов). Оплата — крипто-only (NOWPayments).

**Unit-economics (модель, не факт — pre-revenue):** fixed infra ~$25–35/мес (MVP) → ~$100–135 при $2k MRR;
gross margin Pro/Trader ~97%; **break-even = 2 платящих Pro**; LTV ~$140 (→ ~$280 после E4); referral
$10 → LTV/CAC ≥14; target **$2k MRR за 6 мес** (~40 Pro + 8 Trader). Узкое место — **дистрибуция, не затраты**.

## 4. Состояние роадмапа

Эпики **A–D done** (backend core, landing, SPA, hardening). Текущая волна — **Epic E «Path to revenue»**.

| Эпик | Тема | Статус |
|---|---|---|
| E0 Survival/ops | бэкапы, пул, latency-метрика, embed-cache | **done** |
| E1 First value 30s | packs, instant value, free-delay | **done** |
| E2 Signal quality | baseline, 👍/👎, adaptive threshold | **done** |
| E3 Showcase channel | автопостинг, proof-of-speed, рефералы | **done** |
| E4 Frictionless money | year/quarter, one-click renewal, grace | code-done (Wave F) |
| E5 Pricing | Pro $29 / Trader $99, Free=funnel | **done** |
| E6 Business metrics | activation funnel, MRR dashboard | TASK-050 done; 051 in-progress |
| E7 Cost & scale | global pipeline, event-driven scoring, fallback source | defined |
| E8 New sources/markets | Twitter, B2B fiat, white-label | defined (после $2k MRR) |

Wave F «Activation & polish» — **code done** (15 задач merged), вкл. ребренд в **Foresignal**.
Критический путь до первого доллара по коду закрыт; осталось owner-gated (см. §7).

## 5. Pain points (P1–P8) — что болит сейчас

«Болит сейчас»: **P1** (пул из 1 аккаунта, реальные баны → продукт замолкает), **P3** (~6-мин задержка
сигнала — а продаём скорость), **P8** (бэкапы/restore — один инцидент = конец проекта). **P5** (токены
в БД) — **закрыт** (TASK-032, Fernet at-rest). P2/P4/P6/P7 — «дешёвый defer сейчас, fix forever потом».

## 6. Статус качества сигнала (signal-quality report, 2026-06-13)

Пайплайн был **мёртв в проде** (9404 кластера → 0 scores → 0 alerts, Redis OOM каждые ~20 мин). Сейчас
**жив end-to-end и доказанно осмыслен**:

| Метрика (judged n=35) | До | После |
|---|---|---|
| ROC-AUC score vs viral/noise | 0.564 (≈chance) | **0.859** |
| Spearman | 0.013 | **0.504** |
| precision@1 | 0.00 | **1.00** |
| viral vs noise separation | inverted (−4.57) | correct |

**Честные лимиты:** выборка мала (n=35); **alerts/showcase = 0** (ни одно настоящее вирус-событие ещё не
перешло порог — каналы малообъёмные); текстовый ML-корпус только начал копиться (эмбеддинги персистятся).
*(Позже, 2026-06-14 re-deploy: live `viral_score>0` 18/18 max 31.7.)*

## 7. Открытые owner-gated пункты (MANUAL-TODO)

1. Живой NOWPayments-платёж $29 + проверка IPN → активация подписки.
2. Re-mint мёртвых TG-сессий (TASK-087, 🔴) при AuthKeyDuplicated.
3. **Пул ≥3 аккаунтов (TASK-059, ⛔)** — иначе продукт молчит на бане.
4. Решение: продакшнить публичный `/v1/signals` + MCP (TASK-088, 🟡; ветка не merged).
5. UptimeRobot, email-routing, первый showcase-пост (нужен сигнал ≥ порога).
6. Twitter/X ingest (TASK-031/089/090) — код готов, OFF до `TWITTER_BEARER_TOKEN`.

---

## Связь со скорингом

Текущее ограничение ценности = **сигнал голодает** (мало кросс-канальной широты → мало алертов) и
**показывает не ту метрику**. Это и есть фокус следующего этапа — см. [`02-state-target.md`](./02-state-target.md)
и [`../../architecture/states/03-scoring-evolution-plan.md`](../../architecture/states/03-scoring-evolution-plan.md).
</content>
