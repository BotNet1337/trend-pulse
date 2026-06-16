# Architecture State 02 — Целевое состояние скоринга (TO-BE)

> Куда ведём скоринг и **почему это достижимо** (research + proofs). Парные документы:
> [`01-state-current.md`](./01-state-current.md) (AS-IS), [`03-scoring-evolution-plan.md`](./03-scoring-evolution-plan.md) (план),
> продуктовый target — [`../../product/states/02-state-target.md`](../../product/states/02-state-target.md).

Status: **target proposal (research-backed)** · решения с вариантами (≥5 на узловых точках), рекомендация выделена.

---

## 0. Главный сдвиг рамки (что мы вообще обещаем)

Research-вывод (Cheng 2014, Martin&Watts 2016, Salganik 2006): **«предсказать вирусность с нуля» —
принципиально ограничено** (<50% дисперсии объяснимо даже с бесконечными данными; «удача» Salganik).
А вот **«история уже тронулась — продолжит ли расти?»** предсказуемо: Cheng 2014 даёт **0.795 acc /
0.877 AUC** на сбалансированной задаче «удвоится ли каскад», и временные+структурные фичи доминируют
(контент и автор слабы). Поэтому target-рамка:

> **TrendPulse скорит не «абсолютную будущую вирусность», а калиброванную вероятность того, что уже
> зарождающаяся (первые каналы / 15–60 мин) кросс-канальная история продолжит разгоняться** —
> взвешенно по независимости источников. Это и провабельно, и совпадает с моатом.

Это убирает over-claim и делает каждую метрику дефендебл research-ом (см. §7 proofs).

---

## 1. Целевой поток сигнала (TO-BE)

```mermaid
flowchart LR
    chans[(Public channels · TG→+X→+Reddit)] -->|pool ≥3| C[collector]
    C --> BUF[(Redis buffer)]
    BUF --> B[batch_processor]
    B --> P["pipeline: dedup→normalize→embed→cluster (cross-channel-aware)"]
    P --> DB[(Postgres + pgvector)]
    P -. early-window .-> SNAP[(cluster_feature_snapshots B1)]
    SNAP --> FE["feature builder: breadth, EWMA velocity/accel, Hawkes n*, eff-independent-sources, engagement"]
    FE --> M{scorer}
    M -->|GBDT calibrated p(grow) + formula fallback| SCORES[(scores: p_grow, independence, components)]
    SCORES -->|event-driven trigger| AL[alert]
    DB -->|aggregate| API[/watchlists: p_grow + breadth + independence + sparkline/]
    API --> UI[Signal Desk]
    SCORES -.-> OBS[shadow-eval / online PR-AUC, calibration, alert-precision]
```

**Что нового по сравнению с AS-IS:** (а) кросс-канальная связка темы реально даёт `channels_count>1`;
(б) фичи строятся из B1-снапшотов; (в) live-скорер = **калиброванный GBDT `p(grow)` + formula-fallback**
на холодном старте; (г) **независимость источников** как отдельный множитель/фича и видимый бейдж;
(д) UI показывает `p_grow`+широту+независимость, а не velocity; (е) онлайн shadow-eval метрик.

---

## 2. Узловые решения (каждое — ≥5 вариантов, рекомендация первой)

### D1. Главная live-метрика скоринга

1. **(Рек.) Калиброванный GBDT `p(grow)` + formula-fallback на cold-start.** Higgs PR-AUC 0.920@1ч, Brier 0.106; интерфейс уже написан (`viral_model.py`), фичи идентичны B1. Дефолт при `<2 постов/каналов` → формула.
2. Только улучшенная формула v2.1 (заменить velocity на EWMA-accel), без ML. Дёшево, но потолок ниже.
3. Гибрид: формула выдаёт score, GBDT — только «confidence/grow-flag» поверх. Меньше риск, двойная логика.
4. Логистическая регрессия на тех же фичах (калибруется тривиально, интерпретируема) вместо GBDT.
5. Двухголовый: `p(grow)` (GBDT) для алертов + «magnitude» (регрессия log-engagement) для ранжирования.
6. Ансамбль GBDT+formula по weighted-rank (защита от дрейфа модели).

→ **Рек. 1**, с 5 как next-step (отдельная «сила» для сортировки). Pure-Hawkes как скорер отвергнут (0.70 < 0.81 feature-model, Mishra 2016).

### D2. Как связывать одну тему ПОПЕРЁК каналов (источник широты)

1. **(Рек.) Тюнить cross-batch merge + понизить cosine-порог окна** (`cluster_cosine_threshold` 0.75→кандидат 0.62–0.70) с A/B по распределению `channels_count`. Минимальный диффект, уже есть инфраструктура merge.
2. Двухуровневая кластеризация: tight (0.8, дедуп) → loose (0.6, «история») поверх.
3. Канонические сущности/эвенты (NER + entity-linking) — кластеры вокруг сущности, не центроида.
4. Time-bucketed ANN-merge через pgvector HNSW по всем свежим кластерам (не только per-batch).
5. LSH/MinHash на нормализованном тексте как cheap cross-channel pre-merge до эмбеддинга.
6. Supervised pair-merge (маленькая модель «это одна история?») на разъехавшихся парах.

→ **Рек. 1 → 2** поэтапно; 3/6 — после набора данных. Риск 1: over-merge (cosine вниз склеивает разное) → обязательный замер precision склейки на judged-парах перед деплоем.

### D3. Метрика «скорость/ускорение» вместо дегенеративного velocity

1. **(Рек.) EWMA velocity + EWMA acceleration** (`science_features.py:69–106`) — события/час с весом свежести и знак ускорения. Cheng 2014: темпоральные фичи доминируют.
2. Hawkes branching n\* как фича-режим (sub/supercritical) — диагностика предсказуемости (SEISMIC).
3. Breadth-velocity (distinct-channels/час) — прямой прокси кросс-канального разгона.
4. Burst-z-score: (текущая частота − baseline канала)/σ.
5. Derivative-of-engagement (Δengagement/Δt) сглаженный.
6. Комбинация 1+3 как 2 отдельные фичи в GBDT (а не одна velocity).

→ **Рек. 6** (EWMA-accel + breadth-velocity как две фичи); n\* (2) добавить фичей, не скорером.

### D4. Сигнал независимости источников (moat)

1. **(Рек.) `effective_independent_sources = exp(entropy источников)` как фича GBDT + видимый бейдж**, в паре с baseline-нулём синхронности. Ugander 2012/Weng 2013 проверяют широту-как-предиктор; eff-sources standalone PR-AUC 0.831.
2. + co-forwarding/identical-rebroadcast граф (Telegram-натив, Nature 2025) как anti-collusion дисконт.
3. + temporal-synchrony z-score (одновременный постинг = подозрение на координацию).
4. + content-similarity null-model (CIB, Pacheco 2021) — отделить органик-вирусность от копипасты.
5. Независимость как **множитель** к score (penalize collusion), а не фича.
6. Граф независимости как отдельный «Noise/Trust»-бейдж, не трогая score.

→ **Рек. 1 сейчас**, 2–4 итеративно. ВАЖНО (research-честно): независимость **доказана как предиктор органики, НЕ как готовый детектор координации** end-to-end — поэтому не ship-ить independence-only; парить с synchrony/similarity-нулём (§7 RQ3). Известный false-positive: настоящая вирусность выглядит как координация.

### D5. Как обучать TG-GBDT (данных мало — B0 ~315–964 истории)

1. **(Рек.) Bootstrap на Higgs-артефакте сейчас → дообучение на B1 по мере накопления (target N≥1–2k размеченных исходов).** Фича-схема идентична → swap артефакта без кода.
2. Transfer/fine-tune Higgs→TG (заморозить деревья, докалибровать порог на TG).
3. Полу-supervised: doubling-label (TASK-110 forward-split) на B1, расти онлайн.
4. Weak-labels от текущей формулы + ручной judged-набор (n растёт через 👍/👎).
5. Только калибровка (Platt/Isotonic) Higgs-модели под TG-распределение, без переобучения.
6. Synthetic augmentation на science-генераторе каскадов до набора N.

→ **Рек. 1 (+5 как промежуток)**. Honest gate: PR-AUC 0.92 — на Higgs, НЕ на TG; продакшн-модель ждёт N (см. §7 RQ2, RQ6).

### D6. Latency скоринга (P3 — «продаём скорость»)

1. **(Рек.) Event-driven scoring триггер** при апдейте свежего кластера (вместо tick 300s) — TASK-053. Цель p50 post→alert < 2 мин.
2. Снизить `scorer_interval_seconds` 300→60 (дёшево, грубо).
3. Hot-path: алерт-кандидаты скорить чаще, остальное — реже (двух-скоростной beat).
4. Streaming-инкремент фич в Redis (не пересчёт из Postgres).
5. Push из pipeline в scorer через очередь «hot cluster».
6. Гибрид 2+3: базовый 60s + немедленный re-score кластера, перешедшего порог широты.

→ **Рек. 1 (forever) с 2 как немедленным дешёвым шагом.**

### D7. Объём/перекрытие ingest (без широты нет moat)

1. **(Рек.) Пул ≥3 сессий + curated cross-overlapping packs** (каналы, пишущие об одних событиях). Прямо повышает `channels_count>1`. (Привязано к pool-работе.)
2. Расшить набор каналов на топик (crypto-RU плотный кластер).
3. Добавить 2-й источник (X/Reddit) для cross-platform широты (Zannettou 2017 fringe→mainstream).
4. Seed-паки «событийных» каналов (новостные + агрегаторы) для гарантированного overlap.
5. Снизить порог активности юзера для батча (чаще drain).
6. Backfill истории каналов (ОСТОРОЖНО: не на live-pool-сессии — инцидент AuthKeyDuplicated).

→ **Рек. 1+4 сейчас; 3 — после revenue-гейта.**

---

## 3. Целевые компоненты (delta к AS-IS)

| Слой | AS-IS | TO-BE |
|---|---|---|
| Скорер | v2 формула | калиброванный GBDT `p(grow)` + formula-fallback (D1) |
| Фичи | velocity/engagement/cross_channel | + EWMA accel, breadth-velocity, Hawkes n\*, eff-independent-sources (D3,D4) из B1 |
| Кластеризация | per-batch greedy 0.75 | + loose cross-channel merge, замер precision склейки (D2) |
| Независимость | нет | eff-sources фича + anti-collusion бейдж (D4) |
| Latency | tick 300s (~6 мин) | event-driven < 2 мин (D6) |
| UI-сигнал | акцент velocity | `p_grow` + широта + independence + sparkline (D1) |
| Обучение | offline Higgs | bootstrap→online B1, shadow-eval, калибровка (D5) |
| Ingest | 2 сессии | пул ≥3 + overlapping packs (D7) |

## 4. Целевые метрики успеха (как поймём, что выиграли)

| KPI | AS-IS | Target |
|---|---|---|
| ROC-AUC score vs judged | 0.859 (n=35) | **≥0.88 на n≥150**, стабильно |
| Online PR-AUC `p(grow)` (shadow) | — | **≥0.80@1ч** на TG B1 |
| Калибровка (Brier) | — | **≤0.12** |
| Alert precision@day (👍/👎) | n/a (0 алертов) | **≥0.6** |
| `channels_count>1` доля | ~12% | **≥35%** |
| Latency post→alert p50 | ~6 мин | **<2 мин** |
| Доля кластеров со score>порог | ~0 | стабильный поток истинных алертов |

## 5. Риски и инварианты

- **Over-merge** (D2): склейка разного при низком cosine → обяз. precision-замер на judged-парах.
- **Over-claim вирусности** (D0): не обещаем абсолют; рамка — «продолжит ли расти».
- **Independence-only** (D4): не детектор координации сам по себе → парить с synchrony/similarity-нулём.
- **Higgs≠TG** (D5): не выдавать 0.92 за TG-метрику; gate на N и shadow-eval.
- **CONVENTIONS:** no Any, no magic literals, immutability, leak-free фичи (metrics-only B1), per-user изоляция.

## 6. Связь с офлайн-наработками (всё уже частично есть)

GBDT (TASK-112), science-фичи (TASK-113), quality-gate (TASK-108), forward-split (TASK-110), B1
snapshots (TASK-109, **копятся в проде**), eval-харнессы (TASK-081/085). Target = **подключить и
дообучить**, а не писать с нуля.

## 7. Proofs / research (почему target достижим) — кратко

Полный отчёт с URL — см. [`research/scoring-target-research.md`](../../research/scoring-target-research.md).

- **RQ1 Hawkes/n\*:** [PROVEN частично] SEISMIC (Zhao 2015) ~15% rel.err @1ч; supercritical-blind-spot. n\* — фича, не скорер.
- **RQ2 Early-window GBDT:** [PROVEN] Cheng 2014 0.795 acc/0.877 AUC «удвоится ли»; temporal-фичи в 0.025 от all-features. Mishra 2016 hybrid 0.82 > pure-Hawkes 0.70. Потолок: Martin&Watts <50% дисперсии.
- **RQ3 Source-independence:** [PROVEN как предиктор органики] Ugander 2012 (component-count рулит, volume уходит в минус). CIB-детект (Pacheco 2021) = независимость как нулевая гипотеза. НО end-to-end детектор координации — [INFERENCE], парить с synchrony.
- **RQ4 Cross-community breadth:** [PROVEN] Weng 2013 — первые 50 твитов, cross-community entropy → precision≈0.62/recall≈0.42 (~7×/3.5× над random; +200–350% над community-blind). Ближайший blueprint к нашему скорингу.
- **RQ6 Вердикт:** достижимо для маленькой команды при рамке «conditional growth»; нужно сотни–тысячи размеченных story-исходов; 57.9k-корпус — стартовый, тонкий для robust CV.
</content>
