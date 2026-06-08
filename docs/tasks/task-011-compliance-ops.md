---
id: TASK-011
title: Compliance & ops — 48h retention, GDPR delete-account, rate-limit, observability
status: done        # planned → in-progress → review → done
owner: infra
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "1ec4d5566fd070af67957cd9a48c844e04304d69"
branch: "gsd/phase-011-compliance-ops"
tags: [infra, compliance, gdpr, retention, rate-limit, observability]
---

# TASK-011 — Compliance & ops (48h retention · GDPR delete · rate-limit · observability)

> Закрыть compliance/ops-обязательства из overview §7: Celery beat-задача чистит сырой контент постов старше 48h (остаются метрики+векторы+кластеры), endpoint/команда удаления аккаунта со всеми данными через `ON DELETE CASCADE`, per-user/IP rate-limit на API, и структурное логирование, которое пишет ТОЛЬКО агрегированные метрики (никогда содержимое сообщений) + `/ready` и базовые метрики.

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md)): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon. К этому моменту существуют data-model + multi-tenancy ([task-002](./task-002-data-model.md), `ON DELETE CASCADE` по `user_id`), Telegram-коллектор с Redis-буфером сырых постов ([task-005](./task-005-collector.md)) и alert-delivery ([task-009](./task-009-alert-delivery.md)). Эта задача — финальный compliance/ops-слой Epic A: она не добавляет продуктовых фич, а закрывает регуляторные и эксплуатационные обязательства (overview §7, ADR-002 §4, high-level-arch §4.6/§5 «Observability»).

Compliance-требования зафиксированы в [`../CONVENTIONS.md`](../CONVENTIONS.md) («Compliance: do not persist raw post content beyond the 48h retention window; secrets via env only») и overview §7 GDPR: retention ≤ 48h, удаление аккаунта одним запросом, логировать только агрегированные метрики.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md).

## Goal

После этой задачи: (1) сырой текст постов старше 48h физически удалён — Redis-буфер живёт по TTL, а любой персистнутый raw-text вычищается периодическим sweep'ом; в Postgres остаются только метрики+векторы+кластеры. (2) Один endpoint/команда `DELETE /account` удаляет пользователя и все его строки через `ON DELETE CASCADE` (task-002) без orphan-строк. (3) Превышение лимита на API → `429`. (4) Структурные логи (request + Celery task) содержат только агрегированные метрики, никогда — сырой текст; есть `/ready` (DB+Redis достижимы) поверх существующего `/health` (task-001) и базовые метрики. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения приняты по дефолтам overview/ADR-002; все обратимы. -->
- Q: Чем чистить сырой контент старше 48h? → A: **двухуровнево** → Decision: (a) Redis-буфер сырых постов уже с TTL (task-005) — TTL = 48h в named-constant; (b) Celery beat-задача `purge_expired_raw_content` раз в час делает sweep по любому персистнутому raw-text (поле/таблица сырого контента) и обнуляет/удаляет его, оставляя метрики+векторы (rationale: TTL не покрывает то, что осело в Postgres; ADR-002 §4 требует ≤48h везде).
- Q: Где хранится «сырой текст», который надо чистить sweep'ом? → A: по data-model (task-002) сырой `content` живёт на короткоживущей сущности (напр. `raw_posts`/`posts.raw_text`) с `collected_at`/`created_at` → Decision: purge nullify'ит/удаляет строки, где `now - created_at > RAW_CONTENT_RETENTION_SECONDS`, сохраняя агрегаты (метрики/векторы/кластеры на отдельных таблицах не трогаются). Точное имя поля сверяется по task-002 на шаге locate (rationale: не дублируем схему, опираемся на task-002).
- Q: GDPR delete — endpoint или команда? → A: **оба тонкой обёрткой над одним service-функционалом** → Decision: `DELETE /account` (auth, удаляет текущего юзера) + CLI/make-таргет для оператора; обе зовут `delete_user(user_id)` в `storage`/`api`-сервисе, который делает один `DELETE FROM users WHERE id=:id` и полагается на `ON DELETE CASCADE` (task-002). Проверка отсутствия orphan'ов — частью acceptance (rationale: единый путь, нет дрейфа логики).
- Q: Чем делать rate-limit? → A: **slowapi (Redis-backed)** → Decision: `slowapi` поверх существующего Redis (token-bucket/fixed-window), ключ = `user_id` если аутентифицирован, иначе IP; лимиты — named-constants/env, не магия; превышение → `429` через зарегистрированный handler (rationale: slowapi нативно дружит с FastAPI+Starlette, Redis уже есть; не тащим новый брокер).
- Q: Observability — что именно? → A: derivable из overview §7 + arch §5 → Decision: (a) структурный JSON-логгер (напр. `structlog`/stdlib `logging` с JSON-форматтером) — request-логирование middleware + Celery task-логирование (signals), пишет id'ы/счётчики/длительности, **никогда** `text`/`content`/`raw`; (b) `GET /ready` — readiness-проба (DB `SELECT 1` + Redis `PING`), отдельно от `/health` (liveness, уже есть в task-001); (c) базовые метрики — счётчики обработанных постов/кластеров/алертов + длительности (через тот же логгер или простой `/metrics`-эндпоинт), агрегаты only.
- Q: Что считать «log-leakage»? → A: любое попадание `raw_text`/`content`/тела поста в лог → Decision: log-hygiene — выделенный helper/serializer, который НЕ принимает текстовые поля поста; тест проверяет, что лог не содержит сырого текста (overview §7 «логировать только агрегированные метрики»).
- Q: Применима ли 5.5 security? → A: **ДА** → Decision: applicable: **privacy + rate-limit + log-hygiene** (data-retention/GDPR-delete, rate-limit на endpoints, отсутствие утечки чувствительных данных в логи).

## Scope
> **Раскладка:** задача трогает **только `backend/`** + добавляет beat-расписание; landing/frontend не затрагиваются. Опирается на schema из task-002, буфер/коллектор из task-005, delivery из task-009.

- **Touch ONLY (создать/изменить):**
  - `apps/trendPulse/backend/src/trendpulse/compliance/__init__.py` — новый домен-модуль.
  - `apps/trendPulse/backend/src/trendpulse/compliance/retention.py` — `purge_expired_raw_content()` (sweep по persistnutому raw-text старше `RAW_CONTENT_RETENTION_SECONDS`), pure-ish service над репозиторием.
  - `apps/trendPulse/backend/src/trendpulse/compliance/tasks.py` — Celery task `purge_expired_raw_content_task` (id-only args), регистрация в beat.
  - `apps/trendPulse/backend/src/trendpulse/compliance/account.py` — `delete_user(user_id)` (один `DELETE`, полагается на `ON DELETE CASCADE`).
  - `apps/trendPulse/backend/src/trendpulse/api/routes/account.py` — `DELETE /account` (auth → `delete_user`).
  - `apps/trendPulse/backend/src/trendpulse/api/routes/ops.py` — `GET /ready` (DB+Redis) + базовые метрики.
  - `apps/trendPulse/backend/src/trendpulse/observability/logging.py` — структурный JSON-логгер + log-hygiene helper (агрегаты only).
  - `apps/trendPulse/backend/src/trendpulse/observability/middleware.py` — request-логирование (метод/путь/статус/длительность, без тел).
  - `apps/trendPulse/backend/src/trendpulse/observability/celery_logging.py` — Celery task-signals логирование (имя задачи/длительность/счётчики).
  - `apps/trendPulse/backend/src/trendpulse/api/rate_limit.py` — slowapi limiter (Redis-backed, key=user_id|IP) + `429`-handler.
  - **Изменить:** `apps/trendPulse/backend/src/trendpulse/config.py` (добавить `RAW_CONTENT_RETENTION_SECONDS`, rate-limit лимиты), `scheduler.py` (добавить hourly purge в beat_schedule), `api/main.py` (подключить limiter, middleware, роуты `account`/`ops`), `pyproject.toml` (deps: `slowapi`, JSON-логгер).
  - **Тесты:** `apps/trendPulse/backend/tests/unit/test_retention_purge.py` (AC1 — RED), `tests/unit/test_account_delete.py`, `tests/unit/test_rate_limit.py`, `tests/unit/test_log_hygiene.py`, `tests/unit/test_ready.py`; `tests/integration/test_account_cascade.py` (no-orphan, маркер `integration`).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме `tasks-index.md` на ship), `landing/**`, `frontend/**`. Не менять schema/миграции (это task-002) — только читать; не менять логику коллектора/pipeline/scorer/alerts кроме точки, где они логируют (там — заменить на hygiene-логгер, без изменения поведения).
- **Blast radius:** добавляет global rate-limit на API (может затронуть все endpoint'ы — лимиты дефолтно щедрые/конфигурируемые); меняет формат логов на JSON (потребители логов в ops); добавляет beat-tick; удаление аккаунта необратимо (каскад) — критичный путь, требует auth + явного подтверждения на уровне endpoint.

## Acceptance Criteria
- [ ] **AC1 — retention purge (failing-test anchor).** Given в БД есть raw-text строка с `created_at` 49h назад и строка 1h назад, When вызвать `purge_expired_raw_content()`, Then старая строка — сырой текст удалён/обнулён, свежая — нетронута; метрики/векторы/кластеры обеих сохранены. (Пишется ПЕРВЫМ, RED.)
- [ ] **AC2 — beat планирует purge.** Given поднятый стек, When осмотреть beat_schedule, Then `purge_expired_raw_content_task` запланирован раз в час; задача исполняется worker'ом (виден в логах).
- [ ] **AC3 — GDPR delete, no orphans.** Given пользователь с watchlists/clusters/scores/alerts, When `DELETE /account` (или CLI `delete_user`), Then строка `users` и ВСЕ зависимые строки удалены через `ON DELETE CASCADE`; повторная проверка по всем пользовательским таблицам — 0 строк с этим `user_id` (no orphans).
- [ ] **AC4 — rate-limit → 429.** Given лимит N запросов/окно, When клиент (один `user_id`/IP) превышает лимит, Then ответ `429` с понятным телом; запросы в пределах лимита → `200`.
- [ ] **AC5 — log-hygiene (no raw text).** Given обработка поста с известной уникальной строкой текста, When собрать логи request+Celery-task за цикл, Then логи содержат агрегаты (id'ы/счётчики/длительности) и НЕ содержат сырого текста поста.
- [ ] **AC6 — `/ready`.** Given поднятые DB+Redis, When `GET /ready`, Then `200` + статусы зависимостей `ok`; при недоступной зависимости → `503` (а `/health` остаётся `200`, liveness vs readiness разделены).

## Plan
1. **locate:** сверить по [task-002](./task-002-data-model.md) точное имя сущности/поля сырого текста (`raw_posts`/`posts.raw_text` + timestamp), наличие `ON DELETE CASCADE` на пользовательских FK, и Redis-ключи буфера (task-005); зафиксировать в Details.
2. **config:** добавить named-constants/env в `config.py` — `RAW_CONTENT_RETENTION_SECONDS = 48*3600`, rate-limit лимиты (per-user/IP, окно) — без магических литералов.
3. **retention (TDD):** написать `tests/unit/test_retention_purge.py` (AC1, RED) → реализовать `compliance/retention.py::purge_expired_raw_content()` (репозиторий-запрос по `now - created_at > RAW_CONTENT_RETENTION_SECONDS`, bind-params, не f-string), сохраняя агрегаты.
4. **beat task:** `compliance/tasks.py::purge_expired_raw_content_task` (id-only/без args) + добавить hourly запись в `scheduler.py::beat_schedule`.
5. **GDPR delete:** `compliance/account.py::delete_user(user_id)` (один bind-param `DELETE FROM users`); `api/routes/account.py::DELETE /account` (auth-guard → текущий юзер); integration-тест `test_account_cascade.py` (no-orphan по всем таблицам).
6. **rate-limit:** `api/rate_limit.py` — slowapi `Limiter` (Redis storage из `REDIS_URL`, key-func = `user_id` иначе `get_remote_address`), `429`-handler; подключить в `api/main.py`, навесить дефолтные лимиты.
7. **observability:** `observability/logging.py` (JSON-форматтер + hygiene helper, принимает только агрегаты), `observability/middleware.py` (request-логирование), `observability/celery_logging.py` (Celery `task_prerun`/`task_postrun` signals); заменить точки логирования в pipeline/collector/alerts на hygiene-логгер.
8. **ops endpoints:** `api/routes/ops.py::GET /ready` (DB `SELECT 1` + Redis `PING`, `503` при сбое) + базовые метрики-счётчики; подключить в `api/main.py`.
9. **deps:** `pyproject.toml` — добавить `slowapi` (+ Redis storage extra), JSON-логгер (`structlog` или stdlib + formatter); `uv lock`.
10. **verify (G2):** `make ci-fast`; `make build && make up-d` → проверить AC2 (beat tick в логах), AC3 (`DELETE /account` + проверка orphan'ов), AC4 (превышение лимита → 429 через curl-цикл), AC5 (grep логов — нет сырого текста), AC6 (`curl /ready`/`/health`).

## Invariants
- **Retention ≤ 48h везде** — Redis TTL + Postgres sweep; ни в одной таблице сырой текст не живёт дольше `RAW_CONTENT_RETENTION_SECONDS`. Метрики/векторы/кластеры — сохраняются (ADR-002 §4, overview §7).
- **Логи — только агрегаты.** Никогда не логировать `text`/`content`/`raw_text`/тело поста; log-hygiene helper структурно не принимает текстовые поля (overview §7).
- **Никаких магических литералов** — retention-окно и rate-лимиты в pydantic-settings/env как named-constants, время в секундах.
- **GDPR-delete — единый путь.** Endpoint и CLI зовут один `delete_user(user_id)`; удаление полагается на `ON DELETE CASCADE` (task-002), не дублирует cascade вручную.
- **SQL только через SQLAlchemy bind-params** — purge и delete без f-string SQL.
- **Celery task args JSON-serializable** — purge без args либо id-only; не передавать ORM-объекты.
- **`/health` (liveness) и `/ready` (readiness) разделены** — `/health` не зависит от DB/Redis; `/ready` падает в `503` при недоступности зависимости.
- **Secrets только из env/`.env`** — Redis-URL для rate-limit/ready из настроек, без хардкодов.

## Edge cases
- Persistnutого raw-text может вообще не быть (всё в Redis по TTL) → purge должен быть no-op-safe: 0 строк → не ошибка.
- Гонка: purge во время активного батча юзера → удалять только записи старше окна по `created_at`, идемпотентно; не трогать свежие/in-flight.
- Часовые пояса: сравнение `created_at` в UTC (timezone-aware), иначе off-by-hours при покраске границы 48h.
- GDPR-delete отсутствующего/чужого юзера → endpoint только для текущего аутентифицированного юзера; CLI — явный `user_id`, при отсутствии — понятная ошибка, не молчаливый успех.
- Каскад не настроен на какой-то таблице (дрейф schema) → integration-тест ловит orphan'ы; чинить в task-002, не вручную в delete.
- Rate-limit без Redis (Redis недоступен) → slowapi не должен «фейлить открыто» молча; зафиксировать поведение (degrade/ошибка) и не маскировать.
- Rate-limit key для анонимных за прокси → использовать корректный client IP (учесть `X-Forwarded-For` только если доверенный прокси), иначе все за NAT делят лимит.
- log-hygiene и исключения: трейсбэк не должен включать сырой текст (не класть текст поста в сообщение исключения).
- `/ready` при медленной БД → таймаут на `SELECT 1`/`PING`, чтобы readiness-проба сама не висла.

## Test plan
- **unit:**
  - `test_retention_purge.py` — старая строка очищена, свежая нетронута, агрегаты сохранены (AC1, RED-якорь, фиксированное «now» через инъекцию времени).
  - `test_account_delete.py` — `delete_user` зовёт один `DELETE` по `user_id` (bind-param), endpoint требует auth.
  - `test_rate_limit.py` — N-й+1 запрос → `429`; в пределах лимита → `200` (мок/фейковый стор).
  - `test_log_hygiene.py` — hygiene-логгер с попыткой залогировать пост → в выводе нет сырого текста, есть агрегаты.
  - `test_ready.py` — `/ready` `200` при здоровых зависимостях, `503` при сбое (моки DB/Redis); `/health` остаётся `200`.
- **integration (по требованию, маркер `integration`):**
  - `test_account_cascade.py` — реальный Postgres: создать юзера с зависимыми строками → `delete_user` → 0 строк во всех пользовательских таблицах (no-orphan).
- **runtime/behavioral (G2):** `make build && make up-d` → AC2 (purge tick в логах worker), AC4 (curl-цикл → `429`), AC5 (`make … logs` + grep на отсутствие сырого текста), AC6 (`curl /ready` и `/health`).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "1ec4d5566fd070af67957cd9a48c844e04304d69"
branch: "gsd/phase-011-compliance-ops"
lock: "loop-011"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto — HIGH rate-limit per-user keying + MEDIUM proxy-headers/ready-timeout fixed)
- [x] 5.5 security (REQUIRED — PASS, 0 blocking; no IDOR, no log leak, retention real)
- [x] 6 ship (PR #13, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по overview §7, ADR-002 §4 и high-level-arch §5 «Observability»; зависит от task-002 (schema/CASCADE), task-005 (raw-buffer/TTL), task-009 (delivery). Точные имена raw-text сущности/полей и FK-каскадов сверяются по task-002 на шаге locate.)


### Step 3 do · 4 verify · 5 review · 5.5 security · loop-011
- **do (TDD, FLAT):** `compliance/` (retention.purge_expired_raw_content — bulk UPDATE posts SET text=NULL WHERE fetched_at<now-48h; account.delete_user — single DELETE+CASCADE; tasks.purge task hourly beat), `observability/` (JSON logger + forbidden-key hygiene, request middleware, celery signals — aggregates only), `api/rate_limit.py` (slowapi Redis-backed + in-memory fallback + 429 handler), `api/routes/{account(DELETE /account auth+204),ops(GET /ready DB+Redis 200/503)}`. config: RAW_CONTENT_RETENTION_SECONDS/rate-limit/readiness-timeout. scheduler hourly purge; main.py wires limiter+middleware+routes; /health intact. deps slowapi+python-json-logger (typed). RED→GREEN: test_retention_purge.
- **verify (G2):** ci-fast 227 unit green (mypy strict, compliance+observability в packages). **Полный integration-suite зелёный**: 26 passed (incl. test_account_cascade no-orphan AC3 против реальной БД) / 5 skipped (Redis+ml+telegram env-conditional) / 0 fail. /ready, log-hygiene, retention, rate-limit, GDPR-delete покрыты.
- **review (opus) → 1 HIGH → fixed (debug cycle 1):** rate-limit per-user keying был мёртв (`request.state.user_id` нигде не ставился → всегда IP-ключ). **FIX:** `rate_limit_key` сам декодит auth-cookie/Bearer JWT (HS256, aud fastapi-users:auth, без БД) → `user:{sub}`, иначе `ip:`; +3 теста (два юзера на одном IP → разные бакеты, anon/invalid → IP). MEDIUM: uvicorn `--proxy-headers --forwarded-allow-ips=*` (api только за nginx → реальный client IP для anon-keying); `/ready` redis-проверка bounded `readiness_check_timeout_seconds`. 
- **security (opus) PASS, 0 blocking:** нет IDOR на DELETE /account (только current_user.id, за current_user, 401 anon, cascade без orphan); retention реально обнуляет text>48h; нет утечки raw-text/секретов в логи (forbidden-key denylist + middleware без тел + celery без args); /ready без internal-leak; rate-limit не fail-open (in-memory fallback, не spoofable XFF). Долг (LOW, не блок): in-memory fallback множит лимит на реплики; denylist→allowlist для лог-гигиены; dedicated tighter лимит на DELETE; celery _starts leak при SIGKILL.
