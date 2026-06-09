---
id: TASK-037
title: Кэш эмбеддингов по SHA-256 хэшу нормализованного текста (Redis, TTL 48h)
status: done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e0, backend, pipeline, pain-p2]
---

# TASK-037 — Embedding cache (Epic E0)

> P2-дёшево из [pain-points](../architecture/pain-points.md): один и тот же вирусный пост у 100 юзеров
> эмбеддится 100 раз (самая дорогая операция pipeline). Кэш по хэшу текста снимает ~90% дублей
> маленькой правкой, заодно режет задержку (P3). Глобальный pipeline — потом (TASK-052).

## Context

`pipeline/steps/embed.py::run(posts, encoder=None) -> list[list[float]]` — чистый шаг, lazy-singleton
модель (`embedding_model_name` default `all-MiniLM-L6-v2`, `EMBEDDING_DIM=384`). Вызывается из
`batch_processor._run_pipeline` (pure chain, no I/O) ← `process_user_batch(user_id)` (I/O-слой: Redis drain,
session). Конвенция: pipeline-шаги чистые/immutable → **кэш нельзя класть внутрь `embed.run`**.
Redis: `get_redis_client()`; key-паттерн `raw:{kind}:{handle}`; TTL-паттерн:
`RAW_POST_TTL_SECONDS = 48*60*60` (named Final).

## Goal

Повторный текст (другой юзер/тот же юзер позже) не пересчитывает эмбеддинг: вектор берётся из Redis
по ключу `embed:{model}:{sha256(text)}` с TTL 48ч. Чистота `embed.run` сохранена — кэш живёт на
I/O-слое `batch_processor`. Hit/miss — в structured-лог. DoD = AC.

## Discussion
- Q: Кэш внутри `embed.run`? → A: нет → Decision: шаг остаётся чистым (CONVENTIONS). В `batch_processor`
  появляется обёртка `embed_with_cache(redis, normalized) -> vectors`: partition на cached/uncached →
  `embed.run` только для uncached → merge в исходном порядке → set новых в Redis.
- Q: Ключ? → Decision: `embed:{model_name}:{sha256(normalized_text)}` — model в ключе, чтобы смена
  модели не отдавала вектора чужой размерности; текст уже нормализован (normalize.py) → хэш стабилен.
- Q: Сериализация вектора? → Decision: JSON-массив float (384 значений ≈ 4–8KB) — просто и читаемо;
  bin-упаковка (struct/np.tobytes) — преждевременная оптимизация, отметить как future в learnings.
- Q: TTL? → Decision: новая константа `EMBEDDING_CACHE_TTL_SECONDS = 48*60*60` в `pipeline/constants.py`
  (паттерн `RAW_POST_TTL_SECONDS`; семантически согласована с retention-окном 48ч, но независима).
- Q: Redis недоступен/битое значение? → Decision: fail-open — считаем моделью, warn-лог. Кэш не должен
  ронять pipeline.

## Scope
- **Touch ONLY:**
  - `backend/src/pipeline/batch_processor.py` — `embed_with_cache(...)` + замена вызова `embed.run` в
    `_run_pipeline`→ цепочка получает vectors через кэш-обёртку (сигнатура `_run_pipeline` получает redis
    или vectors — минимальный вариант решает executor, сохранив чистоту `_run_pipeline` если дешевле
    прокинуть уже готовые вектора).
  - `backend/src/pipeline/constants.py` — `EMBEDDING_CACHE_TTL_SECONDS`, `EMBEDDING_CACHE_KEY_PREFIX = "embed"`.
  - tests: `backend/tests/unit/test_batch_processor.py` (дополнить — мок Redis уже паттерн там),
    `backend/tests/unit/test_embed_cache.py` — **новый**.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `pipeline/steps/embed.py` (шаг чистый, API не меняется), `normalize/dedup/cluster`,
  модели/миграции, collector.
- **Blast radius:** только путь `process_user_batch`; рост памяти Redis (вектор ≈4–8KB × уникальных постов
  за 48ч — мониторится TASK-036 `redis_memory`). Поведение при выключенном/пустом кэше идентично текущему.

## Acceptance Criteria
- [ ] **AC1 — hit не зовёт модель (failing-test anchor).** Given два поста с одинаковым текстом в разных
  батчах, When второй батч, Then encoder.encode вызывается 0 раз для повторного текста (fake encoder +
  fake Redis), вектор идентичен закэшированному. RED первым.
- [ ] **AC2 — miss считает и кладёт.** Given новый текст, When батч, Then модель вызвана, в Redis появился
  ключ `embed:{model}:{hash}` с TTL ≈ 48ч и JSON-вектором длины `EMBEDDING_DIM`.
- [ ] **AC3 — порядок и смешанный батч.** Given батч [cached, new, cached], Then итоговые vectors
  параллельны posts в исходном порядке (как контракт `embed.run`).
- [ ] **AC4 — fail-open.** Given Redis бросает на get/set ИЛИ значение битое (не JSON/не та длина),
  Then pipeline считает моделью и не падает; warn-лог; битый ключ перезаписывается.
- [ ] **AC5 — чистота шага + G2.** Given дифф, Then `embed.py` не изменён; `make ci-fast` зелёный;
  G2: в dev два юзера с общим каналом → в логах cache hit (лог `embed_cache` hits/misses), время
  второго батча заметно меньше.

## Plan
1. **RED:** `test_embed_cache.py` — AC1/AC3/AC4 на fake encoder + fake Redis (MagicMock-паттерн из test_batch_processor).
2. `pipeline/constants.py` — TTL/prefix; `batch_processor.embed_with_cache` (sha256, partition, merge, fail-open, log hits/misses).
3. Врезка в `process_user_batch`/`_run_pipeline` (минимальный вариант, чистота сохранена).
4. GREEN + G2 (`make up`, два юзера с общим каналом); tasks-index на ship.

## Invariants
- `embed.run` остаётся чистым и неизменным; контракт «vectors параллельны posts» сохранён.
- Размерность из кэша всегда валидируется (`EMBEDDING_DIM`) — битое значение = miss.
- Кэш fail-open: недоступный Redis не меняет результат, только скорость.
- TTL/prefix — named constants (no magic literals).
- В кэше только вектор (float'ы) — сырой текст в Redis не дублируется сверх существующего буфера (compliance 48h не нарушается: TTL ≤ retention).

## Edge cases
- Пустой текст после normalize → как сейчас (embed получает то же), хэш стабилен — кэшируется наравне.
- Коллизия sha256 — игнорируем (практически невозможна).
- Смена `embedding_model_name` → ключи со старой моделью не читаются (model в ключе), вымрут по TTL.
- Конкурентные батчи считают один miss дважды → допустимо (last-write-wins, значения идентичны).

## Test plan
- **unit:** `test_embed_cache.py` — AC1–AC4; дополнение `test_batch_processor.py` — `process_user_batch`
  с кэшем (мок Redis), поведение без Redis идентично.
- **G2:** dev-стек, общий канал у двух юзеров → `embed_cache` hits>0 в логах; `redis_memory` (TASK-036) без аномалий.
- **security:** не применимо (нет user-input/секретов) — 5.5 скип с пометкой.

## Checkpoints
current_step: done
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: "gsd/phase-e0-embedding-cache"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior; см. Details)
- [x] 5 review (auto, adversarial — pass; MEDIUM element-validation + 2 LOW исправлены)
- [x] 5.5 security (N/A — нет user-input/секретов, скип по test plan)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto — записаны в docs/learnings.md до ship, в том же PR)
debug_runs: []

## Details
(initial — locate: `embed.run` чистый с инжектируемым encoder (тестам удобно), вызов в `_run_pipeline` (pure) ← `process_user_batch` (I/O) — кэш кладём на I/O-границу, чистота конвенции сохранена; key/TTL-паттерны готовы (`raw:{kind}:{handle}`, `RAW_POST_TTL_SECONDS`); мок-паттерн Redis в test_batch_processor.py есть. fakeredis в зависимостях нет — мок/MagicMock. Это заплатка до TASK-052 (глобальный pipeline); cache hit-rate из логов покажет, когда 052 пора.)

2026-06-10 (do→ship): TDD (RED: 8 падений → GREEN: 381 unit, ruff/mypy чисто). Дизайн: `embed_with_cache`
на I/O-слое process_user_batch; `_run_pipeline(posts, vectors=None)` — опциональные предвычисленные
вектора, чистота цепочки сохранена, embed.py не тронут. Принятый tradeoff: dedup+normalize гоняются
дважды (на I/O-слое для ключей и в чистой цепочке) — pure-python, субмиллисекунды; устранение — в
TASK-052 (передавать normalized в _run_pipeline). G2 на живом dev-Redis: miss → ключи embed:{model}:{sha256}
c TTL=172800 и dim=384; hit → энкодер не вызван, вектора идентичны; битый ключ → recompute+overwrite, warn.
Review-фиксы: (1) MEDIUM — валидация элементов кэша (list корректной длины из строк проходил и ронял бы
cluster.run) → элементы обязаны быть int/float не-bool, иначе miss+overwrite; (2) дедуп одинаковых
miss-текстов внутри батча (1 вызов энкодера на уникальный текст); (3) setex-цикл → redis.pipeline
(один round-trip, fail-open сохранён). Real-model прогон скипнут: sentence-transformers только в
worker-образе (arch §7) — поведенческий контракт полностью покрыт fake-encoder'ом против реального Redis.
