---
id: TASK-022
title: Scoring correctness — posts↔cluster FK + per-cluster score + retention/upsert + горячие индексы
status: planned          # planned → in-progress → review → done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: ""
branch: "gsd/phase-022-scoring-correctness"
tags: [epic-d, backend, scorer, data-model, perf]
---

# TASK-022 — Scoring correctness (Epic D)

> P0 продуктовая корректность (learnings task-008). Сейчас scoring работает **per-TOPIC, а не per-cluster** — нет FK `posts.cluster_id`, поэтому `_build_score_inputs` агрегирует посты по watched-каналам темы (а не по постам конкретного кластера), что даёт **дубль-алерты одной темы** и неточный engagement. Плюс `Score` пишется каждый тик без upsert/ретенции, и нет составных индексов на горячих выборках. Задача: (1) FK `posts.cluster_id → clusters.id` (nullable, ON DELETE SET NULL) + проставлять `cluster_id` при персисте кластеров. (2) Scoring per-CLUSTER. (3) `Score` upsert по `(user_id, cluster_id)` ИЛИ retention-sweep по `computed_at` + `ix_scores_cluster`. (4) Составные индексы на горячих путях. ОСТОРОЖНО: не сломать идемпотентность alert (`uq_alerts_user_cluster`) и пайплайн.

## Context

`backend/src/scorer/tasks.py` (док-стринг подтверждает): «cluster carries embedding/topic/timestamps but NOT metrics, and there is no post↔cluster FK. So the score is derived from the user's recent posts on the channels they watch under the cluster's topic … A precise post↔cluster link is a future refinement.» То есть `_topic_configs` группирует watchlists по topic, `_build_score_inputs` суммирует totals по watched-каналам темы за окно — **per-topic**, не per-cluster. Несколько кластеров одной темы → один и тот же score-вход → дубли/смазанный engagement.

Модели (`backend/src/storage/models/`):
- `posts.py`: `__tablename__="posts"`, `channel_id = ForeignKey("channels.id")`, `posted_at`, `Index("ix_posts_user_id","user_id")`. **Нет `cluster_id`.**
- `clusters.py`: `Index("ix_clusters_user_id","user_id")`, `first_seen`, `updated_at`, `topic`.
- `scores.py`: `cluster_id = ForeignKey("clusters.id")`, `computed_at`, `viral_score`, `Index("ix_scores_user_id","user_id")`. `_persist_score` (`tasks.py:155`) делает `session.add(Score(...))` — новая строка каждый тик, без upsert/ретенции.
- `alerts.py`: `UniqueConstraint("user_id","cluster_id","uq_alerts_user_cluster")` — идемпотентность алерта (migration 0003); `_create_alert_idempotent` (`tasks.py:174`) полагается на неё.

Пайплайн кластеризации: `backend/src/pipeline/steps/cluster.py` (+ batch-persist в `pipeline/batch_processor.py`/`pipeline/tasks.py`) — место, где кластеры создаются и куда нужно проставлять `posts.cluster_id`. Миграции — `backend/migrations/versions/` (chain ...`0005_billing`; следующий `0006`/после task-020 — `0007`, executor выверяет порядок). Retention seam — task-011 (`compliance/retention.py`, beat `purge-expired-raw-content`).

Конвенции: tenant-scoped, full type hints, no magic literals (окно/пороги — settings), SQLAlchemy bind-params, mypy strict.

## Goal

После задачи: у `posts` есть FK `cluster_id → clusters.id` (nullable, ON DELETE SET NULL), проставляемый при персисте кластеров; scoring считает engagement **по постам конкретного кластера** (`posts.cluster_id == cluster.id`), а не по всем постам темы → один alert на кластер, без дублей темы; `Score` не плодит строки бесконечно (upsert по `(user_id, cluster_id)` ИЛИ retention-sweep по `computed_at`) + индекс `ix_scores_cluster`; составные индексы на горячих выборках (`posts(user_id, channel_id, posted_at)`, `clusters(user_id, updated_at)`, `scores(user_id, cluster_id, computed_at)`, `alerts(user_id, first_seen)` если не сделан в task-020). Идемпотентность alert (`uq_alerts_user_cluster`) и пайплайн не сломаны. Миграции — корректная chain. unit+integration scorer зелёные. Security N/A.

## Discussion
<!-- durable record of clarifications; обратимы. -->
- Q: Почему дубли алертов? → A: scoring per-topic, кластеров на тему много, alert уникален по `(user_id, cluster_id)` но score-вход одинаков → каждый кластер темы триггерит на одном и том же engagement → визуально дубли одной темы. → Decision: считать engagement по постам кластера (нужен FK), тогда каждый кластер имеет свой реальный engagement.
- Q: FK `posts.cluster_id` — nullable? → A: посты существуют до кластеризации и могут быть вне кластера → Decision: **nullable**, `ON DELETE SET NULL` (удаление кластера/ретенция не каскадит посты). Проставляется на этапе персиста кластеров (батч).
- Q: Где проставлять `cluster_id`? → A: в шаге кластеризации/батч-персисте → Decision: `pipeline/steps/cluster.py` + batch-persist (`batch_processor`/`tasks`) — при сохранении кластера обновлять `cluster_id` его постов (bulk update по id, bind-params). Без N+1.
- Q: `Score` upsert или retention? → A: оба адресуют «строка каждый тик» → Decision: **предпочтительно upsert** по `(user_id, cluster_id)` (обновлять `viral_score`+`computed_at`, не плодить) — нужен unique-constraint на `(user_id, cluster_id)` в scores; **либо** (если история score важна) retention-sweep по `computed_at` (переиспользовать task-011 seam) + `ix_scores_cluster`. Решение исполнителя; AC: scores не растут безгранично на повторных тиках одного кластера.
- Q: Какие составные индексы? → A: горячие выборки scorer/alerts → Decision: `posts(user_id, channel_id, posted_at)` (engagement-агрегация), `clusters(user_id, updated_at)` (`_recent_clusters` freshness), `scores(user_id, cluster_id, computed_at)`, `alerts(user_id, first_seen)` (если task-020 уже создал `ix_alerts_user_first_seen` — НЕ дублировать).
- Q: Риск идемпотентности? → A: `uq_alerts_user_cluster` — основа → Decision: НЕ менять unique-constraint алертов; `_create_alert_idempotent` остаётся; per-cluster scoring только уточняет, какой engagement у `cluster_id`, не трогая ключ алерта.
- Q: Что с постами без кластера (cluster_id NULL)? → A: они не дают per-cluster score → Decision: scoring идёт по кластерам (`_recent_clusters`), берёт их посты по FK; посты без кластера в score-вход кластера не попадают (корректно).

## Scope
> Самая сложная задача эпика: data-model (FK+индексы+миграции), scorer-логика (per-cluster), pipeline-персист (`cluster_id`), score-ретенция/upsert. Меняем модель и scorer; alert-ключ и контракт пайплайна — НЕ ломаем.

- **Touch ONLY (создать/изменить):**
  - `backend/src/storage/models/posts.py` — `cluster_id: Mapped[int | None] = mapped_column(ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True)`; составной `Index("ix_posts_user_channel_posted","user_id","channel_id","posted_at")`.
  - `backend/src/storage/models/clusters.py` — `Index("ix_clusters_user_updated","user_id","updated_at")`.
  - `backend/src/storage/models/scores.py` — `UniqueConstraint("user_id","cluster_id")` (если upsert-путь) ИЛИ `Index("ix_scores_cluster","cluster_id")` + `Index("ix_scores_user_cluster_computed","user_id","cluster_id","computed_at")`.
  - `backend/src/storage/models/alerts.py` — `Index("ix_alerts_user_first_seen",...)` ТОЛЬКО если task-020 его не создал.
  - `backend/migrations/versions/00NN_*.py` — **новые** миграции: add `posts.cluster_id` FK (SET NULL) + backfill-стратегия (NULL ок), составные индексы, scores unique/index. chain после `0005`/task-020 (executor выверяет номер).
  - `backend/src/scorer/tasks.py` — `_build_score_inputs` (и `_recent_clusters` использование): engagement по `posts.cluster_id == cluster.id` (не по всем каналам темы); `_persist_score` — upsert по `(user_id, cluster_id)` ИЛИ оставить insert + retention-sweep.
  - `backend/src/pipeline/steps/cluster.py` + `backend/src/pipeline/batch_processor.py`/`pipeline/tasks.py` — проставлять `posts.cluster_id` при персисте кластеров (bulk, bind-params).
  - `backend/src/compliance/retention.py` + `scheduler.py`/`compliance/tasks.py` — score retention-sweep (если выбран retention-путь, переиспользовать task-011 seam).
  - `backend/tests/unit/test_scorer*.py`, `backend/tests/integration/test_scorer*.py` (+ pipeline-тесты) — per-cluster engagement, один alert на кластер (не дубли темы), upsert/ретенция scores, FK-персист `cluster_id`, миграция chain.
  - `docs/tasks/tasks-index.md` — на ship (оркестратор).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `frontend/**`, `landing/**`, `api/alerts/**` контракт (read-роут не меняем), `alerts/**` delivery-логика (task-009), `uq_alerts_user_cluster` ключ. Не менять формулу `compute_components` (`scorer/score.py`) если не требуется — только источник `ScoreInputs`.
- **Blast radius:** изменение схемы (`posts.cluster_id` FK + индексы + scores constraint) — миграции, влияют на dev/prod БД; per-cluster scoring меняет какие алерты генерятся (продуктовое поведение — меньше дублей); pipeline-персист добавляет write `cluster_id` (нагрузка батча); score upsert/retention меняет рост таблицы. Риск регрессии идемпотентности и пайплайна — основной фокус тестов.

## Acceptance Criteria
- [ ] **AC1 — per-cluster score, один alert на кластер (failing-test anchor).** Given две темы с несколькими кластерами и постами, размеченными по `cluster_id`, When scorer-тик, Then engagement каждого кластера считается по ЕГО постам (`posts.cluster_id == cluster.id`), и на тему с N кластерами не генерится N дублей по одинаковому score-входу — алерты соответствуют реальному engagement кластера. integration пишется ПЕРВЫМ (RED — текущий per-topic даёт дубли).
- [ ] **AC2 — FK `posts.cluster_id` + персист.** Given миграция, When upgrade head, Then `posts.cluster_id → clusters.id` (nullable, ON DELETE SET NULL) существует; при персисте кластера его посты получают `cluster_id` (bulk); удаление кластера → `cluster_id=NULL` (не каскад постов).
- [ ] **AC3 — scores не растут безгранично.** Given повторные тики одного `(user_id, cluster_id)`, When upsert ИЛИ retention-sweep, Then число строк `scores` для пары не растёт линейно с тиками (upsert обновляет computed_at; либо sweep чистит старые по `computed_at`); `ix_scores_cluster` создан.
- [ ] **AC4 — горячие составные индексы.** Given миграции, When upgrade head, Then созданы `ix_posts_user_channel_posted(user_id,channel_id,posted_at)`, `ix_clusters_user_updated(user_id,updated_at)`, `scores(user_id,cluster_id,computed_at)`; `alerts(user_id,first_seen)` присутствует (этой задачей или task-020, без дублей).
- [ ] **AC5 — идемпотентность alert + пайплайн целы.** Given `uq_alerts_user_cluster` и контракт пайплайна, When повторный тик и батч-персист, Then дубль-alert по `(user_id, cluster_id)` по-прежнему не создаётся; pipeline-тесты (нормализация/дедуп/эмбеддинг/кластеризация) зелёные; нет регрессии `_create_alert_idempotent`.
- [ ] **AC6 — тесты + G2.** Given unit+integration scorer (per-cluster, upsert/retention, FK-персист, миграции chain), When прогон + `make up` со скоррингом против реальной БД, Then всё зелёное; engagement baseline учитывает cluster-посты (наблюдаемо). Артефакты on-failure.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-022-scoring-correctness`; выверяет номер миграции относительно task-020.
1. **RED (integration):** сценарий «тема с несколькими кластерами + размеченные `cluster_id` посты» → ожидаем per-cluster engagement и отсутствие дубль-алертов одинакового входа. Падает (per-topic). AC1-якорь.
2. Миграции: `posts.cluster_id` FK (nullable, SET NULL) + составные индексы (`posts`/`clusters`/`scores`) + scores unique/`ix_scores_cluster`; `alerts(user_id,first_seen)` только если нет от task-020. `make migrate`/upgrade head (AC2/AC4).
3. Модели: добавить колонку/индексы/constraint синхронно с миграцией.
4. pipeline: `cluster.py` + batch-персист проставляют `posts.cluster_id` (bulk, bind-params); pipeline-тесты зелёные (AC2/AC5).
5. scorer: `_build_score_inputs` — engagement по постам кластера; `_persist_score` — upsert по `(user_id, cluster_id)` ИЛИ insert+retention-sweep (`compliance/retention.py` seam). (AC1/AC3).
6. Проверить идемпотентность alert (`uq_alerts_user_cluster` + `_create_alert_idempotent`) не задета (AC5).
7. **G2:** `make up` со скоррингом против реальной БД — per-cluster алерты, scores не пухнут; integration+unit зелёные (AC6). Обновить `tasks-index.md` на ship.

## Invariants
- **Per-cluster engagement** — score-вход агрегируется по `posts.cluster_id == cluster.id`, не по всем постам темы; один кластер — один реальный engagement.
- **`uq_alerts_user_cluster` неприкосновенен** — идемпотентность алерта сохраняется; per-cluster scoring не меняет alert-ключ.
- **FK nullable + SET NULL** — посты без кластера допустимы; удаление кластера не каскадит посты.
- **scores ограничены** — upsert по `(user_id, cluster_id)` или retention по `computed_at`; не бесконечный рост на тиках.
- **No magic literals** — окна/пороги/интервалы — settings (как `scorer_recent_window_seconds`); SQL — bind-params.
- **Пайплайн-контракт цел** — `cluster_id`-персист аддитивен; нормализация/дедуп/эмбеддинг/кластеризация не меняют поведение.
- **Миграции — корректная chain** — после `0005`/task-020; down-миграции дропают добавленное.

## Edge cases
- Посты без кластера (`cluster_id NULL`) → не входят в per-cluster score (корректно); scorer не падает на NULL.
- Кластер без постов с проставленным FK (рассинхрон) → engagement 0/skip, не `500`.
- Удаление/ретенция кластера при ON DELETE SET NULL → посты остаются, `cluster_id=NULL`; не сиротеют через каскад.
- Backfill `posts.cluster_id` на проде (исторические посты) → миграция NULL-дефолтом не блокирует; ретро-разметка не требуется (NULL ок).
- Гонка батч-персиста и scorer-тика на одном кластере → upsert/idempotent-alert выдерживают конкуренцию (как migration 0003 нота про concurrent tick).
- scores unique-constraint конфликт при первом внедрении (существующие дубли строк) → миграция чистит дубли до создания unique (иначе upgrade падает).
- `alerts(user_id,first_seen)` уже создан task-020 → не создавать второй раз (проверить existence, избежать конфликта миграций).

## Test plan
- **unit (scorer):** `test_scorer*.py` — `_build_score_inputs` по постам кластера vs темы; `_persist_score` upsert обновляет, не плодит; формула не задета.
- **integration (scorer):** тема с несколькими кластерами → per-cluster алерты без дублей (AC1), идемпотентность `(user_id,cluster_id)` (AC5), scores не растут на повторных тиках (AC3).
- **migration:** upgrade/downgrade head — `posts.cluster_id` FK SET NULL, составные индексы, scores unique/`ix_scores_cluster` (AC2/AC4); chain после `0005`/task-020; `test_migrations.py`.
- **pipeline:** `cluster.py`/batch-персист проставляет `cluster_id` (bulk), pipeline-набор зелёный, контракт цел (AC2/AC5).
- **runtime/behavioral (G2):** `make up` со скоррингом против реальной БД — per-cluster алерты, scores ограничены, engagement учитывает cluster-посты (AC6).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: ""
branch: "gsd/phase-022-scoring-correctness"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior через nginx/стек)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (если применимо)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по проверенным фактам и learnings task-008: `scorer/tasks.py` док-стринг подтверждает per-topic scoring без post↔cluster FK (`_topic_configs`/`_build_score_inputs` агрегируют по watched-каналам темы) → дубли/неточный engagement; `posts.py` без `cluster_id` (есть только `channels.id` FK + `ix_posts_user_id`); `scores.py` `_persist_score` insert каждый тик (`ix_scores_user_id`); `alerts.py` `uq_alerts_user_cluster` (migration 0003) — идемпотентность, НЕ трогаем; кластеры персистятся в `pipeline/steps/cluster.py` + batch-processor; миграции chain `...0005_billing` → executor выверяет номер после task-020; retention seam — task-011 `compliance/retention.py` + beat `purge-expired-raw-content`. deps: 007 (pipeline), 008 (scorer). Security N/A. Самая сложная — детальный plan/edge-cases. locate+plan выполнены — executor стартует с «3 do».)
