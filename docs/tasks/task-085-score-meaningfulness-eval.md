---
id: TASK-085
title: Доказать, что viral_score ОСМЫСЛЕН (а не просто ненулевой) — eval-harness + числа
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "3b1a94c"
branch: "task/085-score-meaningfulness-eval"
tags: [eval, scorer, signal-quality, discrimination, auc, threshold, T14]
---

# TASK-085 — Доказать, что viral_score ОСМЫСЛЕН (T14)

> Скоринг жив в проде (scores текут; цепочка collect→cluster→score работает).
> Владелец явно хочет уверенности, что `viral_score` РАЗУМЕН И ЦЕНЕН: высокий скор =
> «это расходится / стоит алерта», низкий = «шум» — а не просто «числа появились».
> Нужен переиспользуемый eval-harness + отчёт с конкретными числами. Расширяет
> eval-модуль из TASK-081 (`backend/src/eval/`).

## Goal

Расширить `backend/src/eval/` слоями возрастающей строгости (монотонность →
дискриминация → калибровка порога → lead-time PROXY), которые ПЕРЕИСПОЛЬЗУЮТ реальную
`scorer.score.compute_components`/`ScoreInputs` (импорт, НИКОГДА не реимплементация
формулы), и записать реальные произведённые числа в
`cache/trendpulse-signal-quality-report.md` (секция «Score meaningfulness (T14)»).
БЕЗ изменения прод-логики scorer/clustering. БЕЗ frontend/templates.

## Discussion
<!-- durable record -->
- Q: как доказать осмысленность без живых юзеров/фидбэка? → A: двумя источниками
  меток. (1) СИНТЕТИЧЕСКИЕ контролируемые сценарии (viral/noise/borderline) с
  однозначными intended-метками — доказывают дискриминацию *по построению*.
  (2) ВЫБОРКА РЕАЛЬНЫХ прод-кластеров (read-only экспорт), размеченных судьёй-агентом
  по тексту `topic` + метрикам; метки закоммичены в фикстуру для воспроизводимости.
- Q: какие числа отвечают на «ценен ли скор»? → A: ROC-AUC (ранжирование скор vs
  бинарная метка), precision@k (топ-k по скору — реально вирусные?), Spearman (скор vs
  порядковое суждение), separation (mean/median viral vs noise + маржа), confusion на
  нескольких порогах.
- Q: hypothesis в репо? → A: нет → property-стиль через параметризованные кейсы.
- Q: `channel_avg`/`watched` для реальных кластеров? → A: те же PROXY, что в TASK-081
  (cold-channel fallback `views/posts_in_window`; watched=10 допущение) — помечено.
- **Главная находка:** синтетика → AUC=1.0 (формула осмысленна ПО ПОСТРОЕНИЮ), но
  реальный корпус → AUC=0.56, Spearman=0.01, маржа −4.6. Причина: член velocity
  `log1p(Δchannels)/Δhours` ВЫРОЖДАЕТСЯ на одноканальных постах с нулевым окном
  (Δhours→clamp 1 мин ⇒ velocity≈41.6 ⇒ viral≈17.0 у ВСЕХ одиночек), а настоящая
  2-канальная новость за 4ч получает velocity≈0.27 ⇒ viral≈1.6 — ранжирование
  ИНВЕРТИРОВАНО. Это дефект scorer-формулы на backfill-форме корпуса (scorer-side
  фикс, вне scope read-only eval), а не артефакт разметки.

## Acceptance Criteria

- AC1: монотонность/property-тесты (детерминированно, без меток) — каждый драйвер
  двигает скор верно (больше каналов → выше velocity; меньше Δhours → выше velocity;
  numerator>channel_avg → engagement>1 и растёт; шире покрытие → выше cross_channel;
  композит монотонно не убывает по каждому компоненту). ✅ — `test_monotonicity.py`.
- AC2: дискриминация viral vs noise на ДВУХ источниках (синтетика + размеченные
  реальные кластеры); отчёт содержит separation (mean/median), ROC-AUC, precision@k,
  Spearman. ✅ — синтетика AUC=1.0/ρ=0.976/маржа 21.4; реал AUC=0.564/ρ=0.013/маржа −4.6.
- AC3: калибровка порога — confusion на нескольких порогах, текущий дефолт и разумен
  ли он. ✅ — синтетика: чистый разрез ~5; реал: ни один порог не разделяет; 85/90 →
  0 алертов; дефолт watchlist=0.0 → все 35 (precision 0.26).
- AC4: lead-time sanity — помечено как PROXY; на недискриминирующем реал-скоре проверка
  «перешёл бы порог до пика» бессмысленна. ✅ (честно помечено).
- AC5: настоящий runnable harness + тесты чистых хелперов (AUC/precision@k/Spearman/
  separation/confusion). ✅ — `backend/tests/unit/eval/test_metrics.py` (+scenarios).
- AC6: прод-логика scorer/clustering НЕ изменена (только импорт); frontend/templates
  не тронуты; `make test` + `make ci-fast` зелёные. ✅

## Verdict (для владельца, прямо)

Дизайн скора ЗДРАВ и доказуемо осмыслен: идеальная синтетическая AUC=1.0, все
монотонность-тесты зелёные. НО прямо сейчас, на реальных прод-данных, скор НЕ отделяет
вирус от шума (AUC 0.56) — потому что velocity вырождается на одноканальной,
нулевооконной форме корпуса и инвертирует ранжирование. Фикс — scorer-side (пересмотр
clamp `Δhours`/масштаб velocity) + накопление настоящих многоканальных live-данных,
оба вне этого read-only eval. T14 даёт переиспользуемый harness и числа, делающие это
диагностируемым.

## Baseline numbers (фактически измерено, 2026-06-13)

- **Синтетика (n=8, 3 viral):** ROC-AUC **1.000**; separation mean 21.89/0.50 (маржа
  **21.39**); precision@1/3/5 = 1.00/1.00/0.60; Spearman **0.976**.
- **Реал (n=35, 9 viral, судья-агент):** ROC-AUC **0.564**; separation mean
  11.83/16.40 (маржа **−4.57**), median 17.035/17.024; precision@1/3/5 = 0.00/0.33/0.60;
  Spearman **0.013**.
- **Порог (реал):** thr=0 → 9TP/26FP (prec 0.26); thr 5–10 → 6TP/25FP (prec 0.19);
  thr 50/70/85/90 → 0 алертов. Дефолт watchlist `threshold`=0.0; packs 70; showcase 85/90.
- **Корень:** одиночный нулевооконный пост velocity=log1p(1)/(1/60)=41.59 ⇒ viral≈17.03;
  реальная 2-канальная новость (3292, 2ch/4.10h) velocity=0.268 ⇒ viral≈1.596 (оба
  проверены прогоном).

## Caveats

1. Малая выборка реала (35 кластеров, 9 viral) — направление ясно, но не статзначимо.
2. Субъективность судьи — метки закоммичены с обоснованием (`judge_note`); синтетика
   — строгое доказательство, реал — проверка честности.
3. PROXY из TASK-081: `channel_avg` cold-fallback, `watched`=10 допущение.
4. Строгость реал-меток растёт по мере накопления live-данных — harness переиспользуем,
   обновляется только фикстура.

## Files touched

- `backend/src/eval/metrics.py` — чистые ранжир-метрики (ROC-AUC/precision@k/Spearman/
  separation/confusion), numpy-free, exact.
- `backend/src/eval/scenarios.py` — размеченные `(ScoreInputs,label)` наборы: синтетика
  + загрузчик judged-real фикстуры (переиспользуют `compute_components`).
- `backend/src/eval/__init__.py` — docstring расширен (T14).
- `backend/scripts/meaningfulness_eval.py` — runnable CLI (3 слоя + порог).
- `backend/scripts/export_real_judged.sh` — read-only экспортёр оконных агрегатов.
- `backend/data/eval/real_judged.sample.csv` — закоммиченная judged-real фикстура (35).
- `backend/tests/unit/eval/test_monotonicity.py`, `test_metrics.py`, `test_scenarios.py`.
- `cache/trendpulse-signal-quality-report.md` — секция «Score meaningfulness (T14)».
- `docs/tasks/task-085-score-meaningfulness-eval.md`, `docs/tasks/tasks-index.md`.

## Tests

`make test` (unit) + `make ci-fast` (ruff format/check + mypy ×2) — зелёные.
`backend/tests/unit/eval/` — 49 новых unit-тестов (монотонность 13; метрики 23;
сценарии 13) поверх 28 из TASK-081 = 77 в eval-пакете. Harness реально запущен
(синтетика + judged-real) — числа выше из его вывода.

## Checkpoints

- [x] lock: agent-a5746e1eeaebce684
- [x] locate
- [x] plan (G1)
- [x] do (TDD)
- [x] verify (G2) — make test + ci-fast
- [x] review
- [x] ship — PR #128 https://github.com/BotNet1337/trend-pulse/pull/128 (MERGED)
- current_step: ship
