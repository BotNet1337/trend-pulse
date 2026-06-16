# TrendPulse / Foresignal — План трансформации (2026-06-15)

Источник: системный аудит (надёжность), конкурентная разведка, научный обзор виральности +
датасеты, ревью кода скоринга и продуктовых доков. Цель владельца: **(1)** сервис работает
недели без правок кода и стабилен на 100%; **(2)** скоринг не просто выдаёт число, а реально
ценен (высокий, осмысленный сигнал → прогноз сбывается); **(3)** максимум источников для
точности; **(4)** качественный рывок (алгоритм/ML/решение проблемы данных); продукт, который
можно продавать.

---

## 0. Где мы сейчас (честная картина)

**Скоринг — НЕ сломан (память устарела).** `scorer/score.py` уже v2: engagement-dominant
(0.55 / 0.30 / 0.15), все компоненты ∈ [0,1], score ∈ [0,100], thresholdable. На judged-корпусе
real ROC-AUC ≈ 0.86; на чистом forward-time-split (eval_offline/harness2) ≈ 0.91–0.93. Формула
**осмысленна по конструкции** и теперь дискриминирует. Но: (а) она **ручная**, не выученная;
(б) валидирована на крошечном/прокси-корпусе; (в) `docs/product/overview.md §4` показывает старую
формулу (drift).

**Надёжность — код-фиксы крепкие, но для «недель без присмотра» есть show-stopper'ы.** Историчные
инциденты (Redis OOM, буферы, AuthKeyDuplicated, scores=0) **исправлены в коде**, не «залатаны
вживую». Реальные риски многонедельного автономного прогона:
- **FM-1 (CRITICAL):** TG-пул = 1 сессия (`POOL_MIN=1`). Permanent auth error → ingest молча
  встаёт для ВСЕХ тенантов, один alert «раз», дальше тишина. Нет авто-восстановления.
- **FM-2:** карантин сессии — in-memory; рестарт воркера «разкарантинивает» мёртвую сессию →
  повторный спам-alert, сожжённый tick.
- **FM-3:** нет liveness-healthcheck на `worker`/`beat` → зависший-но-живой процесс не детектится.
- **FM-4:** Celery result-keys не истекают (`result_expires` не задан) в том же 224mb Redis →
  риск OOM-rejection enqueue'ов (политика `noeviction`).
- **FM-5:** внешний uptime-watchdog (UptimeRobot /api/ready) owner-gated, не активен → детекция
  падений завязана на self-alert воркера (циклично: воркер мёртв → alert не уйдёт).

**Проблема данных — корень всего.** Корпус single-channel, backfill-shaped, 0 живых юзеров,
0 feedback. Реальный потолок качества поднимается ТОЛЬКО с настоящими multi-channel live-данными.
Это главное ограничение «доказать ценность».

**Источники.** TG — live. Twitter/X — построен, owner-gated (token, pay-per-use, бюджет 100k
reads/мес). Reddit — построен (PR #160-162), owner-gated на ключ. Больше независимых источников =
сильнее cross-channel сигнал = точнее прогноз.

**Конкуренты (разведка).** Никто не делает cross-channel виральность на Telegram (esp. crypto-RU) +
явный independence/collusion-граф. TG-инкумбенты (TGStat/Telemetr) — per-channel статистика +
keyword-алерты, без story-кластеризации и ранней виральности. Crypto-social (LunarCrush/Santiment/
Kaito/The TIE) — Twitter-центричны, скорят токены, не истории, Telegram игнорят. NewsWhip — единственный
предиктивный аналог (Holt-проекция engagement к 2× возрасту), но 0 Telegram, enterprise-цена.
**Незанятый клин подтверждён.** Чего у нас нет, а у них есть: bot/collusion-детект, sentiment,
influencer/authority-вес, открытый backtesting наружу, API/MCP.

**Наука (что работает).** GBDT на early-window фичах — high-ROI путь (XGBoost: PR-AUC 0.43@30мин →
0.80@420мин). Лейбл без юзеров: self-supervised forward time-split, задача «удвоения» Cheng (AUC 0.88).
Сильнейшие фичи: temporal velocity/acceleration + cross-channel breadth + Hawkes infectiousness
(Mishra hybrid: параметры точечного процесса как фичи). Content/sentiment — слабые (и у нас текст
purged через 48ч — ОК, топовые модели и так без текста). Потолок: <50% дисперсии cascade size
объяснимо в принципе (Martin 2016) → целимся в калиброванную вероятность, не детерминизм.
Публичные датасеты для bootstrap: **Pushshift Telegram** (27.8k каналов, views+forwards+forward-graph),
**TeraGram** (5.9B msgs, +reactions, RU-heavy), Weibo/Higgs/MemeTracker (temporal cascade-бенчмарки).

---

## 1. Четыре трека трансформации

### Track A — НАДЁЖНОСТЬ (приоритет владельца #1) — «работает недели без присмотра»
Цель: убрать все show-stopper'ы автономного прогона. В основном код (часть — owner-gated секреты).

| # | Задача | Файл/где | Owner-gate? |
|---|--------|----------|-------------|
| A1 | Liveness-healthcheck на `worker` (`celery inspect ping`) | `release/compose/worker.yml` | нет |
| A2 | Beat-heartbeat: beat пишет TS в Redis, probe проверяет свежесть | `release/compose/beat.yml` + `scheduler.py` | нет |
| A3 | Персистентный карантин сессий (Redis set по fingerprint), переживает рестарт | `collector/telegram/account_pool.py` | нет |
| A4 | `result_expires` (короткий) + `task_ignore_result=True` для периодиков | `celery_app.py` | нет |
| A5 | Alert-правило: Redis-память→224mb И ingest-staleness (нет постов N мин) | `observability/` | нет |
| A6 | Эскалирующий/повторяющийся alert при полном исчерпании пула | `collector/telegram/reader.py` | нет |
| A7 | Redis persistence (appendonly) ИЛИ задокументировать bounded-loss маркера | `release/compose/redis.yml` | нет |
| A8 | TG-пул ≥3 сессии, `POOL_MIN=3` | `collector/constants.py` + provision | **да** (нужны номера) |
| A9 | Активировать внешний uptime-probe на `/api/ready` (dead-man switch) | TASK-060 (код есть) | **да** (настройка) |

### Track B — ДАННЫЕ (решаем проблему данных) — фундамент под «доказать ценность» и ML
Параллельно с A. Без этого C невозможен.

| # | Задача | Суть |
|---|--------|------|
| B1 | **Forward feature-snapshot capture (T11)** | На каждый кластер логировать снимок фичей в `T_obs` (15м/30м/1ч) в новую таблицу `cluster_feature_snapshots` (метрики, НЕ raw text — compliance ок). Будущий лейбл = engagement/breadth в `(T_obs, T_label]`. Так строим СВОЙ labeled-датасет из живого потока — продукт сам себе генерит данные. |
| B2 | **Bootstrap offline-датасет** | Скачать Pushshift Telegram + (опц.) TeraGram, привести к схеме фичей; Weibo/Higgs/MemeTracker — для калибровки темпоральной модели. Положить в `eval_offline/data/`. |
| B3 | **Расширить eval-harness** | Forward time-split, задача «удвоения» Cheng (balanced binary), репорт PR-AUC vs окно наблюдения, калибровка. Переиспользовать `backend/src/eval/` метрики. |
| B4 | Активировать доп. источники для РЕАЛЬНОГО cross-channel | Twitter/X + Reddit (owner-gated ключи/бюджет) → genuine multi-channel live data, который и есть потолок качества. |

### Track C — СКОРИНГ/ML РЫВОК (зависит от B)
| # | Задача | Суть |
|---|--------|------|
| C1 | **GBDT-модель** (XGBoost/LightGBM) на early-window фичах, self-supervised «удвоение» | Тренировка на B1+B2; cold-start fallback = текущая ручная v2-формула. |
| C2 | Фичи из науки: EWMA velocity+acceleration; cross-channel breadth-velocity; **Hawkes infectiousness/branching** (Mishra hybrid — параметр процесса как фича); time-of-day (TiDeH). |
| C3 | **Effective independent sources = exp(H)** (энтропия источников) — independence-discount в score (это и есть моат + анти-syndication). |
| C4 | Channel-authority вес (TunkRank-style), не сырые подписчики. |
| C5 | Обновить `docs/product/overview.md §4` под v2/ML (убрать drift). |

### Track D — МОАТ-ФИЧИ (дифференциация, продаваемость) — инкрементально
| # | Задача | Суть |
|---|--------|------|
| D1 | **Collusion/bot-граф** | Pacheco co-channel/co-URL → TF-IDF → cosine → community detection; CooRnet перцентильное окно. Анти-накрутка + ad-filter. Превосходит «Cheater Tag» TGStat/Telemetr. |
| D2 | Origin tracing | Кто первый поднял историю (по timestamp+forward-graph). |
| D3 | Sentiment (опц., t≈0 cold-start) | Слабый предиктор, но дифференциатор vs TG-инкумбентов. |
| D4 | Surface backtesting наружу | У нас уже есть `eval_offline/` — показать клиенту как proof (никто из конкурентов не даёт). |
| D5 | API + MCP-сервер | Table-stakes (LunarCrush/Santiment уже с MCP); signal-first API — открытая ниша. |

---

## 2. Рекомендуемая последовательность

1. **Track A целиком (код-часть A1–A7) ПЕРВЫМ** — без стабильности всё остальное на песке. Это
   разблокировано (секреты не нужны). A8/A9 — owner-gated, идут параллельно как owner-action.
2. **Track B параллельно A** — B1 (snapshot capture) + B3 (harness) — код, разблокировано. B2
   (датасеты) — скачивание, разблокировано. B4 — owner-gated (ключи).
3. **Track C после B** даёт данные — обучение GBDT, новые фичи, валидация.
4. **Track D инкрементально** — D1 (collusion) и D4 (backtesting наружу) — самые продаваемые, D5 (API/MCP) — дёшево и нужно.

## 3. Механика исполнения (как договорено)

Per-задача: `/trendpulse-plan` → `/trendpulse-execute` (locate → TDD → verify G2 → review →
security? → ship → learnings) → **реальная проверка локально + ручной тест** → **деплой на сервер +
ручной тест**. Автономно через `/loop`. Источник истины прогресса — frontmatter `status` +
Checkpoints в task-доках + `tasks-index.md`. Мёрж-политика как в предыдущих лупах (перманентно-красные
depsec/openapi-drift чеки → `--admin`).

## 4. Owner-gates (нужны решения/ресурсы владельца)
- **A8:** реальные телефонные номера для ≥3 TG-сессий (single biggest reliability SPOF).
- **A9:** настройка внешнего uptime-monitor на `/api/ready`.
- **B4/источники:** X API bearer token (+ бюджет, pay-per-use) и Reddit client id/secret/user-agent.
- **Прод-деплой:** право автономного лупа деплоить на `167.233.81.243` после локальной проверки,
  или останавливаться на PR+local-verify и оставлять деплой владельцу. (NB: live TG-сессия пула —
  НЕ ТРОГАТЬ; backfill НИКОГДА на pool-сессии — историчный инцидент AuthKeyDuplicated.)
