# Architecture State 03 — План эволюции скоринга (AS-IS → TO-BE)

> Пошаговый план перехода от [`01-state-current.md`](./01-state-current.md) к [`02-state-target.md`](./02-state-target.md).
> Серия **surgical-задач** (как с пулом): каждая = свой `trendpulse-plan` → `trendpulse-executor`,
> малый дифект, **проверка на проде по факту** (psql/логи + Playwright по UI). Никаких «вслепую».

Status: **plan — awaiting owner "выполнять"** · принцип: smallest-first, видимая ценность раньше.

---

## 0. Порядок ценности и зависимости

```
S0 (eval-gate, готовим измерение) ──► S1 (UI: показать реальный сигнал, БЫСТРО) 
                                         │
S7 (ingest-объём) ──────────► S2 (кросс-канальная широта) ──► S3 (velocity→EWMA/accel)
                                         │                          │
                                         └──────────► S4 (ML serving GBDT) ◄── S0
                                                          │
                                S5 (независимость источников) ──► S6 (latency event-driven)
```

**Рекомендованный порядок исполнения:** **S1 → S0 → S2 → S3 → S4 → S5 → S6**, с **S7 (ops/ingest) параллельно**.
Обоснование: S1 — мгновенный видимый выигрыш на уже посчитанных данных; S0 включает измерение до изменений
модели; S2 даёт широту (основа всего); S3/S4 — качество; S5 — моат; S6 — скорость.

> Каждая Sx ниже — заготовка task-дока. На «выполнять» прогоняем `/trendpulse-plan` по каждой (материализует
> в `docs/tasks/task-NNN-*.md` с checkpoints), затем `/trendpulse-executor`. ID присвоит plan.

---

## S1 — UI/API: показать реальный сигнal (quick win)
- **Цель:** в `/watchlists` «Live signal» показывать `viral_score` (0–100) + тренд по `sparkline_24h`
  (он уже по viral_score); velocity убрать/во вторичные. Скоры avg≈21 уже есть → видно сразу.
- **Scope (файлы):** `api/watchlist/{service,schemas}.py`, `storage/repositories/signal_repo.py` (уже отдаёт
  `live_score`/`sparkline_24h`), фронт `signal-desk.ts` / `watchlist-row.tsx`.
- **Варианты подачи (≥5):** см. [P1 в product target](../../product/states/02-state-target.md#5-узловые-продуктовые-решения-5-вариантов) — рек. вариант 2 сейчас.
- **Проверка (прод-факт):** Playwright на `/watchlists` под суперюзером показывает score>0 + sparkline;
  `scores` в БД подтверждает значения.
- **DoD:** UI не показывает «×0.0» когда `viral_score>0`; нет регрессии API-контракта.
- **Риск/блокирующее:** малый; чисто presentational + выбор поля.

## S0 — Eval-gate: онлайн-измерение до изменений модели
- **Цель:** включить shadow-eval, чтобы любые S3/S4 мерились по факту (PR-AUC, calibration/Brier, alert-precision
  по 👍/👎) на TG-данных, а не на Higgs.
- **Scope:** `eval/metrics.py`, `eval/forward_split.py` (есть offline), новый лёгкий online-сборщик на
  `cluster_feature_snapshots` (B1, копятся) + outcome-join; дашборд-эндпоинт в `api` (admin).
- **Варианты (≥5):** (1)**Рек.** offline-джоб по B1+исходам еженедельно; (2) live shadow-scoring параллельно
  формуле; (3) ручной judged-набор через 👍/👎; (4) реплей-харнесс на накопленном корпусе; (5) A/B логирование
  обеих метрик; (6) calibration-only монитор (Brier на формуле).
- **Проверка:** джоб выдаёт PR-AUC/Brier на TG B1; число размеченных исходов растёт.
- **DoD:** есть воспроизводимая цифра качества на TG до того, как менять модель. Leak-free (forward-split).

## S2 — Clustering: кросс-канальная связка темы (широта = основа моата)
- **Цель:** одна история across каналов = ОДИН кластер с `channels_count>1` (цель ≥35% multi-channel).
- **Scope:** `pipeline/batch_processor.py` (`_find_mergeable_cluster`), `pipeline/steps/cluster.py`,
  `config.py` (`cluster_cosine_threshold`, merge-окна).
- **Варианты (≥5):** см. [D2 в arch target](./02-state-target.md#d2) — рек. 1 (тюнинг merge + loose cosine)
  → 2 (two-tier tight/loose). Обязательно: **замер precision склейки на judged-парах ПЕРЕД деплоем** (over-merge риск).
- **Проверка (прод-факт):** распределение `channels_count` на проде сдвигается (multi-channel доля растёт),
  при этом precision склейки на judged-наборе не падает.
- **DoD:** ≥35% кластеров multi-channel без роста ложных склеек; re-валидация в `eval_offline/`.
- **Зависит от:** S7 (без объёма каналов широты не будет физически).

## S3 — Velocity/acceleration: заменить дегенеративную метрику
- **Цель:** убрать дегенеративный velocity (AUC≈0.07 на сыром корпусе), ввести EWMA-velocity + EWMA-accel
  + breadth-velocity как фичи.
- **Scope:** `scorer/score.py`, `eval/science_features.py` (готово offline), `scorer/tasks.py` (`_build_score_inputs`).
- **Варианты (≥5):** см. [D3](./02-state-target.md#d3) — рек. 6 (две фичи: EWMA-accel + breadth-velocity); n\* — фичей.
- **Проверка:** ре-валидация в `eval_offline/` (PR-AUC/Spearman) ПЕРЕД деплоем; после — прод-факт по `scores`.
- **DoD:** velocity-терм перестаёт быть ≈0 на реальных кросс-канальных историях; AUC не ниже текущего 0.859.

## S4 — ML serving: подключить GBDT `p(grow)` + formula-fallback
- **Цель:** live-скорер зовёт `scorer/viral_model.py` (GBDT + fallback) на B1-снапшотах; формула — cold-start.
- **Scope:** `scorer/tasks.py` (`score_tick`/`_persist_score`), `scorer/viral_model.py` (готов), артефакт
  `models/`, `storage/models/scores.py` (+колонка `p_grow`/`model_choice` для observability).
- **Варианты (≥5):** см. [D1](./02-state-target.md#d1) и [D5](./02-state-target.md#d5) — рек. bootstrap на
  Higgs-артефакте + калибровка под TG (Platt/Isotonic), swap артефакта без кода когда N≥1–2k.
- **Проверка:** `scores` отражают модель; offline PR-AUC/Brier (S0) на TG; ratio GBDT-vs-fallback в логах.
- **DoD:** `p(grow)` калиброван (Brier≤0.12 на TG shadow), fallback стабилен на cold-start, без Any/magic-literals.
- **Зависит от:** S0 (измерение), B1-объём.

## S5 — Источник-независимость (moat-сигнал)
- **Цель:** `effective_independent_sources` как фича GBDT + видимый бейдж; в паре с synchrony/similarity-нулём.
- **Scope:** `eval/science_features.py` (eff-sources готов), `scorer/tasks.py`, `api/watchlist/schemas.py` (бейдж),
  фронт story/row.
- **Варианты (≥5):** см. [D4](./02-state-target.md#d4) — рек. 1 (фича+бейдж) сейчас, +co-forwarding граф (2),
  +temporal-synchrony (3), +content-similarity null (4) итеративно. Honest: independence ≠ детектор координации сам по себе.
- **Проверка:** бейдж рендерится (Playwright); фича влияет на ранжирование на judged-наборе; не растят FP «органик=накрутка».
- **DoD:** independence видим в UI + входит в скоринг; парный baseline синхронности задокументирован.

## S6 — Latency: event-driven scoring (P3 «продаём скорость»)
- **Цель:** post→alert p50 < 2 мин.
- **Scope:** `scheduler.py`, `pipeline/tasks.py`/`scorer/tasks.py`, очередь «hot cluster».
- **Варианты (≥5):** см. [D6](./02-state-target.md#d6) — рек. 1 (event-driven trigger) forever, 2 (interval 300→60)
  немедленно дёшево.
- **Проверка:** метрика p50/p95 post→alert (TASK-036 metric) падает; нагрузка beat/worker в норме.
- **DoD:** p50 < 2 мин на проде без роста стоимости/нестабильности.

## S7 — Ingest-объём (ops, параллельно) 
- **Цель:** поднять перекрытие каналов → физическая основа широты для S2/S3.
- **Scope:** пул-сессии (готово инфраструктурно после store-only QR-revive), curated overlapping packs,
  (позже) 2-й источник X/Reddit.
- **Варианты (≥5):** см. [D7](./02-state-target.md#d7) — рек. 1 (пул ≥3 + overlapping packs) + 4 (event-паки).
- **Проверка:** каналов/час ↑, доля multi-channel кластеров ↑.
- **DoD:** пул ≥3 здоровых сессий; packs с гарантированным overlap; **owner-gated** (покупка номеров, TASK-059).
- **⚠ Hazard:** не backfill-ить на live-pool-сессии (инцидент AuthKeyDuplicated, [[trendpulse-tg-session-incident]]).

---

## Глобальные инварианты (для всех Sx)
- CONVENTIONS: no Any, no magic literals, immutability, leak-free фичи (metrics-only B1), per-user изоляция,
  файлы <800 строк, ошибки не глотать.
- Каждая Sx: locate → do(TDD) → verify(G2: tests+lint+typecheck+runtime+behavioral) → review (другой моделью)
  → security? → ship (PR) → learnings.
- **Каждая проверка — по факту:** psql на проде + Playwright по UI; «работает» только с доказательством.
- Деплой только из чистого worktree (vault-hazard, [[trendpulse-deploy-vault-hazard]]).

## Owner-gates (нужно решение/действие владельца)
- S7: покупка ≥2 номеров для пула (TASK-059, ⛔).
- S4/S5: согласие на изменение скоринг-логики в проде (влияет на алерты).
- Источники X/Reddit: ключи/бюджет (owner-gated, отдельные эпики).
</content>
