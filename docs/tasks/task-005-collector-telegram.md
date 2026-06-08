---
id: TASK-005
title: Source abstraction + Telegram collector — SourceCollector port, Telethon pool, cross-tenant dedup
status: done           # planned → in-progress → review → done
owner: backend
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "73d2bbfb4c0b3fb623ac0113dd5cade00fb8b183"
branch: "gsd/phase-005-collector-telegram"
tags: [backend, collector, telegram, telethon, redis, source-abstraction, multi-tenancy, adr-001, adr-002]
---

# TASK-005 — Source abstraction + Telegram collector (порт · пул · cross-tenant dedup)

> Ввести единый порт `SourceCollector` + нормализованную доменную модель (`SourceKind`, `SourceRef`, `RawPost`, `PostMetrics`) ровно как в [ADR-001](../architecture/adr-001-source-abstraction.md), реализовать Telegram-коллектор на Telethon (пул из 3–10 технических аккаунтов, `FLOOD_WAIT` → exponential backoff + ротация), маппинг Telegram-сущностей → `RawPost`, и читать **объединённое** множество уникальных `SourceRef` по всем активным watchlist'ам (cross-tenant dedup, [ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md)) с буферизацией сырых постов в Redis ключом по источнику и TTL ≤ 48h.

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md)): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon. Это **главный мульти-источниковый шов** ([ADR-001](../architecture/adr-001-source-abstraction.md)): pipeline/scorer работают только с `RawPost`/`NormalizedPost` и ничего не знают о платформе, поэтому Twitter/X (Фаза 4) подключается новой реализацией `SourceCollector` без переписывания ядра. Сейчас реализуем **только Telegram**.

Источник истины по подходу к мониторингу — overview §2 (почему не userbot пользователя: `session_string` = полный доступ к аккаунту, нарушение ToS §5.2 → только пул технических аккаунтов) и §7 (compliance: только публичные каналы, FLOOD_WAIT → backoff+ротация, сырой контент ≤ 48h). Cross-tenant дедупликация источников — [ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md) §3: канал, на который подписаны N юзеров, читается **один раз**.

Окружение и каркас пакета `trendpulse` (src-layout, модуль `collector/`) подготовлены в task-001; схема (`channels`, `watchlists`, `source_kind`) — в task-002 (**зависимость**). Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md).

## Goal

В `backend/src/trendpulse/collector/` появляется: (1) платформо-независимый порт `SourceCollector` + доменная модель (`base.py`) и in-code `registry.py` (`SourceKind → SourceCollector`); (2) Telegram-реализация на Telethon с пулом технических аккаунтов, backoff+ротацией на `FLOOD_WAIT`, маппингом сущностей → `RawPost`; (3) сбор по объединённому уникальному множеству `SourceRef` всех активных watchlist'ов с записью сырых постов в Redis-буфер ключом по источнику и TTL ≤ 48h. Никаких user `session_string` — только пул-креды из env. Всё проверяемо через `make …`; DoD — Acceptance Criteria ниже.

## Discussion
<!-- durable record of clarifications. Решения приняты по ADR-001/002 и overview §2/§7; обратимы. -->
- Q: Где живёт контракт источника? → A: **`collector/base.py`** — `SourceKind(StrEnum)`, `SourceRef`/`RawPost`/`PostMetrics` (frozen dataclasses), `SourceCollector(Protocol)` с `validate_ref` и async `read(refs, since) -> AsyncIterator[RawPost]` → Decision: дословно по [ADR-001](../architecture/adr-001-source-abstraction.md); rate-limit/backoff/ротация инкапсулированы внутри реализации, наружу не торчат (rationale: pipeline/scorer остаются платформо-независимыми).
- Q: Twitter сейчас писать? → A: **нет** (scope guard ADR-001) → Decision: `SourceKind.TWITTER` присутствует в enum как future-маркер, но реализации нет; пустой контракт не пишем, плагинную загрузку/DSL не вводим — простой in-code `registry.py`.
- Q: Откуда креды аккаунтов пула? → A: **только env / pydantic-settings** → Decision: `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` + список session-строк **технических** аккаунтов пула из env (3–10 шт.); **никогда** user `session_string` (overview §2/§7, CONVENTIONS «secrets via env»). Креды не логируются.
- Q: Как реагировать на `FLOOD_WAIT`? → A: overview §7 / ADR-001 §44 → Decision: exponential backoff (named-constant база/cap в секундах) + **ротация на следующий аккаунт пула**; если все аккаунты во FLOOD_WAIT — backoff и повтор, не падать.
- Q: Дедупликация каналов между юзерами? → A: [ADR-002](../architecture/adr-002-multi-tenancy-and-queues.md) §3 → Decision: коллектор читает **UNION уникальных `SourceRef`** по всем активным watchlist'ам; каждый канал читается один раз; сырые посты в общий Redis-буфер **ключом по источнику** (не по юзеру) — фильтрация по watchlist'у юзера происходит позже, на батче (task-007).
- Q: Где буфер и какой TTL? → A: Redis (storage), TTL ≤ 48h → Decision: ключ `raw:{kind}:{handle}` (или эквивалент по источнику), TTL — named constant `RAW_POST_TTL_SECONDS ≤ 48*3600` (overview §7 retention, ADR-002 §4). Сырой контент дальше Redis не утекает.
- Q: Что именно `read` отдаёт и как тестировать без живого Telegram? → A: async-итератор `RawPost`; Telethon-клиент за тонким интерфейсом → Decision: маппинг `tg entity → RawPost` — **чистая функция**, тестируется на фикстуре сущности без сети (AC1 RED-якорь); пул/итерация — на мок-клиенте; один behavioral-прогон (G2) против реального публичного канала.
- Q: `validate_ref` для приватного/битого хэндла? → A: overview §2 «только публичные» → Decision: `True` только для публичного канала, доступного пулу; приватный/несуществующий/некорректный хэндл → `False` (не исключение наружу).

## Scope
> Эта задача трогает **только** `backend/src/trendpulse/collector/**` (+ тонкая точка к Redis-буферу через `storage`-интерфейс) и тесты. Pipeline/scorer/api/alerts/billing — не трогаем; они уже спроектированы на `RawPost` (ADR-001).

- **Touch ONLY (создать):**
  - `apps/trendPulse/backend/src/trendpulse/collector/__init__.py` — публичный реэкспорт порта и модели.
  - `apps/trendPulse/backend/src/trendpulse/collector/base.py` — `SourceKind(StrEnum)`, `SourceRef`, `PostMetrics`, `RawPost` (frozen dataclasses), `SourceCollector(Protocol)` (дословно ADR-001).
  - `apps/trendPulse/backend/src/trendpulse/collector/registry.py` — in-code реестр `SourceKind → SourceCollector` (`register` / `get`), без плагинной загрузки.
  - `apps/trendPulse/backend/src/trendpulse/collector/errors.py` — доменные ошибки коллектора (`SourceUnavailable`, `AllAccountsFloodWait` и т.п.), без bare `except`.
  - `apps/trendPulse/backend/src/trendpulse/collector/telegram/__init__.py`.
  - `apps/trendPulse/backend/src/trendpulse/collector/telegram/account_pool.py` — пул из 3–10 технических аккаунтов (session-строки пула из env), выбор/ротация, состояние FLOOD_WAIT по аккаунту.
  - `apps/trendPulse/backend/src/trendpulse/collector/telegram/mapper.py` — **чистая** функция `tg entity → RawPost` + нормализация `PostMetrics` (views/forwards/reactions → общий вид; платформо-специфика в `metrics.extra`).
  - `apps/trendPulse/backend/src/trendpulse/collector/telegram/reader.py` — `TelegramCollector(SourceCollector)`: `validate_ref`, async `read(refs, since)`; backoff+ротация на `FLOOD_WAIT`; UNION уникальных `SourceRef`, чтение канала один раз.
  - `apps/trendPulse/backend/src/trendpulse/collector/buffer.py` — запись `RawPost` в Redis-буфер ключом по источнику с TTL ≤ 48h (named constant) через storage-Redis-клиент.
  - `apps/trendPulse/backend/src/trendpulse/collector/constants.py` — `RAW_POST_TTL_SECONDS`, база/cap backoff в секундах, лимиты пула (named constants, не magic literals).
  - `apps/trendPulse/backend/tests/unit/collector/test_mapper.py` — AC1 RED-якорь (`tg entity → RawPost`).
  - `apps/trendPulse/backend/tests/unit/collector/test_validate_ref.py`, `test_account_pool_rotation.py`, `test_registry.py`, `test_cross_tenant_dedup.py`, `test_buffer_ttl.py`.
  - `apps/trendPulse/backend/tests/integration/collector/test_telegram_read.py` — behavioral (маркер `integration`, реальный публичный канал).
  - `apps/trendPulse/backend/tests/unit/collector/__init__.py`, `tests/integration/collector/__init__.py`, фикстуры в `conftest.py`.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме обновления `tasks-index.md` на ship), `landing/**`, `frontend/**`; `pipeline/**`, `scorer/**`, `api/**`, `alerts/**`, `billing/**`; `development/**` и `pyproject.toml` (Telethon/redis уже добавлены в task-001 — если внезапно нет, это отдельная правка с пометкой). Не вводить Twitter-реализацию (ADR-001 scope guard). Не менять схему БД (task-002).
- **Blast radius:** задаёт контракт `RawPost`/`SourceCollector`, на который завязаны **task-007** (pipeline на `RawPost`) и **task-008** (scorer на нормализованных metrics); буфер ключом по источнику читает **task-006/007** (drain по watchlist'у). Изменение полей `RawPost`/`PostMetrics` после этой задачи — ломающее для downstream.

## Acceptance Criteria
- [ ] **AC1 — маппинг (RED-якорь).** Given фикстура Telegram-сущности (message/channel) без сети, When `map_entity(entity) ` (чистая функция из `telegram/mapper.py`), Then возвращается `RawPost` с корректными `source`/`external_id`/`author`/`text`/`media_hashes`/`posted_at` (tz-aware UTC) и нормализованными `PostMetrics` (views/forwards/reactions), платформо-специфика — в `metrics.extra`. (тест пишется ПЕРВЫМ, FAIL до реализации).
- [ ] **AC2 — `validate_ref`.** Given `TelegramCollector` с мок-/реальным пулом, When `validate_ref(SourceRef(TELEGRAM, '@public_channel'))`, Then `True`; для приватного / несуществующего / некорректного хэндла → `False` (без проброса исключения наружу).
- [ ] **AC3 — `read` отдаёт нормализованные посты (behavioral, G2).** Given реальный публичный канал и пул-креды из env, When `async read([ref], since)`, Then итератор отдаёт ≥1 `RawPost` с заполненными нормализованными метриками; rate-limits соблюдены (маркер `integration`).
- [ ] **AC4 — FLOOD_WAIT → backoff + ротация.** Given мок-клиент, бросающий `FloodWaitError` на первом аккаунте, When `read`, Then коллектор применяет exponential backoff и **переключается на следующий аккаунт пула**, чтение завершается успешно; при FLOOD_WAIT на всех аккаунтах — backoff и повтор, не падение.
- [ ] **AC5 — cross-tenant dedup (один канал — одно чтение).** Given два активных watchlist'а разных юзеров, оба содержащие один и тот же `@channel`, When коллектор формирует множество для чтения, Then канал присутствует **ровно один раз** (UNION уникальных `SourceRef`) и читается один раз.
- [ ] **AC6 — Redis-буфер ключом по источнику с TTL ≤ 48h.** Given прочитанные `RawPost`, When запись в буфер, Then посты лежат ключом **по источнику** (не по юзеру) и каждому ключу выставлен TTL `RAW_POST_TTL_SECONDS ≤ 48*3600`.
- [ ] **AC7 — реестр.** Given `registry.get(SourceKind.TELEGRAM)`, Then возвращается `TelegramCollector`; `SourceKind.TWITTER` объявлен, но реализация не зарегистрирована (future-маркер).
- [ ] **AC8 — нет user session_string.** Given конфиг коллектора, When инициализация пула, Then креды берутся только из env (пул технических аккаунтов); в коде/логах отсутствует понятие user `session_string`, секреты не логируются (compliance overview §2/§7).

## Plan
0. Executor фиксирует `baseline_commit`; branch `gsd/phase-5-collector-telegram`. Убедиться, что task-002 (схема `channels`/`watchlists`/`source_kind`) и Telethon/redis-зависимости (task-001) на месте.
1. **AC1 RED-first:** написать `tests/unit/collector/test_mapper.py` на фикстуре Telegram-сущности → ожидаемый `RawPost`; прогнать, убедиться FAIL.
2. `collector/base.py` — `SourceKind(StrEnum)` (`TELEGRAM`, `TWITTER` future), `SourceRef`/`PostMetrics`/`RawPost` (frozen dataclasses), `SourceCollector(Protocol)` (`kind`, async `validate_ref`, async `read(refs, since) -> AsyncIterator[RawPost]`) — дословно ADR-001.
3. `collector/constants.py` — `RAW_POST_TTL_SECONDS` (≤ 48*3600), `BACKOFF_BASE_SECONDS`/`BACKOFF_CAP_SECONDS`, `POOL_MIN/POOL_MAX` (3/10). `collector/errors.py` — доменные ошибки.
4. `telegram/mapper.py` — чистая `map_entity(...) -> RawPost` + нормализация `PostMetrics` (extra для платформо-специфики). Прогнать AC1 → GREEN.
5. `telegram/account_pool.py` — загрузка session-строк пула из pydantic-settings (env), выбор активного аккаунта, ротация, per-account FLOOD_WAIT-состояние с backoff. Тест `test_account_pool_rotation.py` (AC4) на моках.
6. `telegram/reader.py` — `TelegramCollector`: `validate_ref` (AC2), async `read`: построение **UNION уникальных** `SourceRef` (AC5), чтение каждого канала один раз, на `FloodWaitError` → backoff+ротация (AC4), маппинг через `mapper`. Тест `test_cross_tenant_dedup.py` (AC5), `test_validate_ref.py` (AC2).
7. `collector/buffer.py` — запись `RawPost` в Redis ключом по источнику с TTL (AC6) через storage-Redis-клиент. Тест `test_buffer_ttl.py`.
8. `collector/registry.py` + `__init__.py` — регистрация `TELEGRAM → TelegramCollector`; `test_registry.py` (AC7).
9. `tests/integration/collector/test_telegram_read.py` — behavioral G2 (реальный публичный канал, маркер `integration`, env-креды) для AC3.
10. Прогнать `make ci-fast` (unit зелёные) и `make test-integration` (AC3 вживую при наличии env-кред); проверить AC2/AC4/AC5/AC6/AC7/AC8.

## Invariants
- **Платформо-независимое ядро.** `base.py` не импортирует Telethon; pipeline/scorer видят только `RawPost`/`PostMetrics`. Telegram-специфика заперта в `collector/telegram/**`.
- **Никогда user `session_string`.** Только пул технических аккаунтов; креды исключительно из env/pydantic-settings; секреты не логируются (overview §2/§7, CONVENTIONS).
- **Только публичные каналы.** `validate_ref` пропускает только публичные; приватные/битые → `False`, не исключение наружу.
- **Сырой контент ≤ 48h.** Буфер — Redis ключом по источнику с TTL `RAW_POST_TTL_SECONDS` (named constant); сырой контент не персистится в Postgres и не утекает за пределы буфера (overview §7, ADR-002 §4).
- **Cross-tenant dedup.** Читается UNION уникальных `SourceRef`; один канал — одно чтение, независимо от числа подписанных юзеров (ADR-002 §3).
- **FLOOD_WAIT не роняет коллектор.** Всегда exponential backoff + ротация аккаунтов; backoff/TTL/лимиты — named constants в секундах, не magic literals.
- **Pydantic/валидация на границе.** Внешние Telegram-данные не доверяются как есть — маппер нормализует и валидирует поля (tz-aware UTC, типы метрик).
- **Чистый маппер.** `map_entity` не мутирует вход и не делает сетевых вызовов (immutable, тестируем без Telegram).
- **Full type hints, без bare `Any`/`# type: ignore`/bare `except`** (CONVENTIONS forbidden patterns); кросс-модульно — через публичные функции `collector`.

## Edge cases
- Все аккаунты пула одновременно во FLOOD_WAIT → backoff и повтор (не падать, не терять `read`).
- Приватный / несуществующий / переименованный `@handle` → `validate_ref=False`; в `read` такой ref пропускается с доменной ошибкой/логом, остальные читаются.
- Пустой канал или нет постов с `since` → итератор отдаёт 0 элементов (не исключение).
- Удалённый/служебный пост, пост без текста (только медиа) → `text=""`, `media_hashes` заполнены; пост-сервис (joined/pinned) отфильтрован.
- Один и тот же `@channel` в разном регистре/с `https://t.me/` префиксом → нормализуется к одному `SourceRef` (UNION действительно уникален, AC5 не ломается).
- Telethon отдаёт naive datetime → маппер приводит к tz-aware UTC.
- Reactions/forwards могут отсутствовать в старых сущностях → нормализуются в 0, не `None` (scorer ожидает числа).
- Размер пула < 3 или > 10 / пустой список session-строк → fail-fast при инициализации с понятной ошибкой (POOL_MIN/POOL_MAX).
- Redis недоступен при записи буфера → доменная ошибка, не молчаливое проглатывание; пост не теряется без следа в логе.

## Test plan
- **unit (RED-first AC1):** `test_mapper.py` — `map_entity(fixture) == ожидаемый RawPost` (нормализованные метрики, tz-aware UTC, extra). Пишется ПЕРВЫМ, FAIL до реализации.
- **unit:** `test_validate_ref.py` (AC2, мок-пул: public→True, private/bad→False), `test_account_pool_rotation.py` (AC4, мок бросает `FloodWaitError` → backoff+ротация, all-flood→повтор), `test_cross_tenant_dedup.py` (AC5, два watchlist'а с общим каналом → один `SourceRef`), `test_buffer_ttl.py` (AC6, ключ по источнику + TTL ≤ 48h), `test_registry.py` (AC7, TELEGRAM зарегистрирован, TWITTER нет).
- **integration (по требованию, маркер `integration`):** `test_telegram_read.py` — реальный публичный канал, пул-креды из env → `read` отдаёт ≥1 `RawPost` с метриками, rate-limits соблюдены (AC3).
- **runtime/behavioral (G2):** `make ci-fast` (unit зелёные); `make test-integration` для AC3 при наличии env-кред; ручная проверка AC8 (нет user session_string, секреты не в логах).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "73d2bbfb4c0b3fb623ac0113dd5cade00fb8b183"
branch: "gsd/phase-005-collector-telegram"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial — PASS; 1 HIGH lifecycle leak fixed)
- [x] 5.5 security (PASS, 0 blocking — secrets env-only, no user session, public-only, 48h TTL)
- [x] 6 ship (PR #6, squash-merged)
- [x] 7 learnings (auto)
debug_runs:
  - cycle: 1
    where: "collector/telegram/{account_pool,reader}.py + live integration test"
    symptom: "review HIGH: pool clients connect() on acquire but never disconnect() → socket/session leak in long-lived worker; live test emitted 'coroutine ignored GeneratorExit'"
    fix: "AccountPool.aclose() disconnects all clients (best-effort, logged); TelegramCollector.aclose() + async context manager; live integration test wraps usage in `async with`. +2 unit tests (aclose disconnects all; __aexit__ disconnects). Re-verify: ci-fast 76 passed; live integration 2 passed, no GeneratorExit warning." 

## Details
<!-- executor appends iterative fixes + decisions here -->
: <!-- HALT --> Луп остановлен на TASK-005 (правило: нужен секрет/решение). AC3 (живое чтение реального публичного канала, G2) требует реальных пул-кредов `TELEGRAM_API_ID/API_HASH` + session-строк 3–10 технических аккаунтов, и egress-сети для worker (сейчас worker только в internal:true сетях — нет интернета). Пользователь предоставит креды; инструкция по получению — в ответе ассистента. Остальные AC (1,2,4,5,6,7,8) реализуемы/проверяемы без сети. После получения кредов: создать ветку gsd/phase-005-collector-telegram, реализовать, верифицировать вкл. живой AC3, ship.

### Step 3 do · 4 verify · loop-20260608-resume-005 · PASS
- **do (TDD, FLAT layout `backend/src/collector/`):** платформо-независимый порт ADR-001 (`base.py`: SourceKind/SourceRef/PostMetrics/RawPost/SourceCollector — без telethon), `registry` (TELEGRAM зарегистрирован lazy, TWITTER future), `errors`, `constants` (RAW_POST_TTL_SECONDS=172800, backoff, POOL_MIN/MAX), `telegram/{client,account_pool,dedup,mapper,reader}`, `buffer` (Redis ключ по источнику + TTL≤48h). config: `telegram_pool_sessions`. RED→GREEN: `test_mapper.py` (ModuleNotFound→7 passed). ci-fast зелёный (mypy strict 50 файлов; 74 unit). telethon lazy-import, no-user-session подтверждён, секреты не логируются.
- **USER-DECISION:** `POOL_MIN=1` (старт с одной dev-сессией; вернуть к 3 при полном пуле). POOL_MAX=10.
- **verify (G2):** AC1 mapper (unit) · AC2 validate_ref True/False (unit+live) · **AC3 живое чтение `@telegram`** — integration 2 passed (с реальной пул-сессией) + прямой прогон `TelegramCollector.read()` отдал RawPost'ы с норм. метриками (views/fwd/reactions) и tz-aware UTC · AC4 FLOOD_WAIT backoff+ротация (unit, mock) · AC5 cross-tenant dedup (unit) · AC6 buffer TTL (fakeredis) · AC7 registry · AC8 no-user-session. ci-fast 74 passed.
- **EGRESS:** добавлена не-internal сеть `egress` только для `worker` (collector→MTProto). compose config валиден; изоляция сохранена (api/postgres/redis без egress).
- **Known (для review):** live integration-тест даёт варнинг `coroutine ignored GeneratorExit` — Telethon-клиент пула не дисконнектится в тесте/после read (lifecycle клиентов пула). Некритично (тест passed), но review оценит как возможный resource-leak.

(initial — план составлен по ADR-001 (source abstraction) + ADR-002 (cross-tenant dedup/retention) + overview §2/§7; depends on task-002. Это мульти-источниковый шов: контракт `RawPost`/`SourceCollector` фиксируется здесь и потребляется task-007/008.)


### Step 5 review (opus) · PASS · Step 5.5 security (opus) · PASS — both 0 blocking
- **review:** ADR-001 platform-independence clean (base.py no telethon, frozen models, telethon lazy in telegram/**); dedup/48h-TTL/FLOOD_WAIT-rotation/named-constants/pure-mapper correct; egress worker-only (api/pg/redis isolated). 1 **HIGH** (client connection leak) → FIXED in debug cycle 1 (aclose + context manager). Non-blocking left: MEDIUM flood mid-iteration re-yields already-emitted msgs (absorbed by external_id dedup; documented), INFO ADR-001 model divergence (author Optional, fetched_at omitted, since Optional — intentional).
- **security:** secrets (api_id/hash/sessions) env-only, never logged (held in factory closure, not in _Account/repr); sensitive.env gitignored+untracked; no user session_string; public-channel read-only; 48h TTL (172800s); egress worker-only; pure mapper, no eval/SSRF. **Action item (NOT blocking, user's):** rotate `TELEGRAM_API_HASH` — it was shared in plaintext chat earlier (NOT committed to git). Pool StringSession not tracked. **POOL_MIN=1** is a documented bootstrap concession → raise to 3 when full pool provisioned.

### Step 6 ship · PR #6 (squash-merged). Step 7 learnings · docs/learnings.md (TASK-005).
