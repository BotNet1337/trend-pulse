---
id: TASK-086
title: Фикс вырождения velocity — viral_score снова осмыслен на реал-данных (T15)
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-13
updated: 2026-06-14
baseline_commit: "de121e5"
branch: "task/086-fix-velocity-degeneration"
tags: [scorer, velocity, signal-quality, discrimination, auc, T15]
---

# TASK-086 — Фикс вырождения velocity (T15)

> T14 (TASK-085) ДОКАЗАЛ дефект: член `velocity = log1p(Δchannel_count)/Δhours` с
> clamp `Δhours → MIN_WINDOW_HOURS` (1/60 ч) на одноканальном/одиночном кластере даёт
> `log1p(1)/(1/60) ≈ 41.6`, что доминирует в `0.4·velocity` → кластер ≈17 (почти
> максимум). На реал-корпусе (harness T14): настоящая 2-канальная новость за 4ч ≈1.6,
> а каждый одиночный пост ≈17 → ранжирование ИНВЕРТИРОВАНО, real ROC-AUC = 0.564 (≈
> монетка). Принцип продукта: «вирус» = история, РАСХОДЯЩАЯСЯ ПО КАНАЛАМ. Одиночный
> пост на ОДНОМ канале не имеет межканального распространения → его velocity ≈ 0.

## Goal

Наименьший фикс scorer, чтобы одноканальные / нулевого-распространения кластеры НЕ
скорились как вирусные, а многоканальные всплески ранжировались выше — и ДОКАЗАТЬ это
тем же harness T14. Scope: только `scorer/score.py` (+ expectations harness/тестов, если
формула требует) + тесты + отчёт + task-doc. БЕЗ frontend/templates/collector/pipeline.

## Discussion
<!-- durable record -->
- Q: какой минимальный фикс? → A: `velocity = log1p(max(Δchannel_count − 1, 0)) / Δhours`.
  1 канал → `log1p(0)=0` (нет межканального распространения → velocity 0); 2 → `log1p(1)`;
  далее монотонно растёт с шириной распространения. Clamp `Δhours` оставлен (защита от
  деления на 0), но при `Δch ≤ 1` числитель = 0, поэтому clamp больше не может породить
  ложную velocity.
- Q: трогать ли engagement/cross_channel или веса? → A: НЕТ. Эмпирически прогнал harness
  с одним только фиксом velocity — инверсия исчезает, real AUC 0.564 → 0.859. Веса не
  менялись (smallest diff). engagement не инвертирует ранжирование — он и есть остаточный
  сигнал для одноканальных кластеров.
- Q: согласован ли `Δch − 1` с тем, как строится `delta_channel_count`? → A: да.
  `scorer.tasks._build_score_inputs`: `delta_channel_count = unique_channels_count =
  #distinct channels in-window`. Одиночный пост → 1 канал → `Δch − 1 = 0`. Семантика
  «лишние каналы сверх своего» точна.
- **Главная находка (прогнано):** velocity-фикс ОДИН возвращает осмысленность на реал-
  данных: real ROC-AUC 0.564 → 0.859, Spearman 0.013 → 0.504, precision@1 0.00 → 1.00,
  separation flip −4.575 → +0.317 (viral теперь ВЫШЕ noise). Синтетика без изменений
  (AUC 1.0, вирус ранжируется топом).

## Acceptance Criteria

- AC1: `_velocity` для 1 канала = 0 (нет межканального распространения), монотонно растёт
  с числом каналов, безопасен при `Δhours → 0`. ✅ — новые unit-тесты в `test_score.py`
  (single=0, two>0, monotonic 1..11, guard Δhours=0 с ≥2 каналами).
- AC2: композит/монотонность не сломаны — синтетические вирусные кейсы всё так же ранжируются
  топом, монотонность по каждому драйверу держится. ✅ — `test_monotonicity.py` (без правок,
  пары начинаются с 1→2: `log1p(0)<log1p(1)` ⇒ держится), синтетика AUC=1.0.
- AC3: harness T14 прогнан на синтетике И на закоммиченной judged-real фикстуре ПОСЛЕ
  фикса; отчёт содержит before/after AUC/Spearman/precision@k/separation. ✅ — секция «T15
  velocity fix — before/after» в `cache/trendpulse-signal-quality-report.md`.
- AC4: real-data AUC существенно выше 0.564 в сторону синтетической 1.0, viral mean ВЫШЕ
  noise. ✅ — **0.564 → 0.859**, viral mean 0.724 > noise 0.407.
- AC5: scope — тронут только `scorer/score.py` + harness-warning + тесты + отчёт + доки;
  frontend/templates/collector/pipeline не тронуты; `make test` + `make ci-fast` зелёные. ✅

## Verdict (для владельца, прямо)

**Фикс делает скор осмысленным на реальных данных.** Real ROC-AUC прыгает с уровня монетки
(0.564) до **0.859**, separation viral-vs-noise ПЕРЕВОРАЧИВАЕТСЯ с инвертированного на
правильный (viral теперь ВЫШЕ noise), а топ-1 и топ-3 реальных кластера теперь все настоящие
вирусные (precision@1: 0 → 1.0). Синтетическая дискриминация остаётся идеальной (AUC=1.0) —
фикс не разменял синтетику на реал. Остаточный потолок 0.859 (не 1.0) — **ограничение
корпуса, не дефект формулы**: 34 из 35 размеченных кластеров одноканальны, у них velocity=0
и ранжирование держится на engagement/cross_channel; настоящий потолок поднимется только с
накоплением многоканальных live-данных (T11). Рекомендация: **шипить фикс** (убирает
доказанную инверсию и восстанавливает рабочий порог алерта ≈1.0 с precision 1.0 на реале);
следующий рычаг качества — многоканальные live-данные, а не очередная правка формулы.

## velocity fix (точная правка)

```python
# scorer/score.py  _velocity()
# было:
return math.log1p(delta_channel_count) / hours
# стало (T15):
extra_channels = max(delta_channel_count - 1, 0)
return math.log1p(extra_channels) / hours
```

## Numbers (фактически измерено harness, 2026-06-13)

| Метрика | BEFORE (T14) | AFTER (T15) |
|---|---:|---:|
| REAL ROC-AUC (n=35, 9 viral) | 0.5641 | **0.8590** |
| REAL Spearman | 0.0128 | **0.5041** |
| REAL precision@1 / @3 / @5 | 0.00 / 0.33 / 0.60 | **1.00 / 1.00 / 0.60** |
| REAL separation viral/noise mean (margin) | 11.829 / 16.404 (−4.575) | 0.724 / 0.407 (**+0.317**) |
| SYNTHETIC ROC-AUC / Spearman | 1.0000 / 0.9759 | **1.0000 / 0.9759** |
| REAL threshold=1.0 (TP/FP, precision) | (всё ≈17, разреза нет) | **3/0, precision 1.000** |

## Caveats

1. Потолок 0.859 — ограничение корпуса: 34/35 кластеров одноканальны (velocity=0),
   ранжирование среди них на engagement/cross_channel. Не дефект формулы.
2. Малая выборка реала (35, 9 viral) — направление ясно, но не статзначимо.
3. PROXY из TASK-081/085 сохраняются: `channel_avg` cold-fallback, `watched`=10 допущение.
4. harness-warning переписан: старое предупреждение про clamp `Δhours` устарело (после
   фикса clamp не порождает velocity); теперь сообщает про одноканальное покрытие корпуса.

## Files touched

- `backend/src/scorer/score.py` — `_velocity`: `log1p(max(Δch − 1, 0))/Δhours` + docstring
  модуля/функции; **единственное изменение прод-логики**.
- `backend/scripts/meaningfulness_eval.py` — `_warn_velocity_clamp` переписан под пост-фикс
  реальность (одноканальное покрытие вместо устаревшего clamp-предупреждения); убран
  неиспользуемый импорт `MIN_WINDOW_HOURS`.
- `backend/tests/unit/test_score.py` — `_expected` + hand-computed value под новую формулу;
  новые/обновлённые `_velocity` тесты (single=0, two>0, monotonic, guard).
- `cache/trendpulse-signal-quality-report.md` — секция «T15 velocity fix — before/after».
- `docs/tasks/task-086-fix-velocity-degeneration.md`, `docs/tasks/tasks-index.md`.

## Tests

`make test` (811 unit passed) + `make ci-fast` (ruff format/check + mypy ×2 + 811 unit) —
зелёные. TDD: RED (3 фейла в `test_score.py`: single-channel velocity 0.347 вместо 0,
hand-computed value, log1p-over-hours) → фикс `_velocity` → GREEN (94 scorer+eval тестов).
harness реально прогнан на синтетике + judged-real — before/after числа из его вывода.

## Checkpoints

- [x] lock: agent-a5a482a3c371c120e
- [x] locate
- [x] plan (G1)
- [x] do (TDD)
- [x] verify (G2) — make test + ci-fast
- [x] review — code-reviewer APPROVE, 0 findings (correctness/scope/no dead refs)
- [x] ship — PR #129 https://github.com/BotNet1337/trend-pulse/pull/129 (NO merge; orchestrator validates+merges+redeploys)
- current_step: done (awaiting orchestrator merge + redeploy)
