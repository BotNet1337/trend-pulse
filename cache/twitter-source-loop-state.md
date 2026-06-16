# Twitter-source loop — STATE  ✅ ЦИКЛ ЗАВЕРШЁН 2026-06-14

> ЦИКЛ ОКОНЧЕН. Все 4 фазы выполнены, 5 PR смержены (#148/#149/#151/#152/#153). Остаток —
> только owner-gated живые чеки (TWITTER_BEARER_TOKEN, перевыпуск TG-сессий, T7 owner-decision)
> + TASK-091 (C7 граф) deferred. Если придёт scheduled-wakeup финализации — он увидит это и просто
> завершится. Память обновлена: trendpulse-twitter-source-loop.


> Источник истины для следующей итерации. Старт с ЧИСТОГО контекста: читать ТОЛЬКО этот файл
> + task-doc(и) + vault (docs/CLAUDE.md, CODEMAPS, CONVENTIONS, ADR). Не таскать транскрипт.

Обновлено: 2026-06-14 (итерация 2).

## Текущая фаза
**ФАЗА 0/A/B ✅ (PR #148/#149/#151).  ФАЗА C идёт:** TASK-031 PR-A (collector ядро) ✅ СМЕРЖЕН
(PR #152 → main `7e90bff`, CI зелёный кроме фронт-esbuild). PR-B (storage SourceKind.TWITTER + per-source handle) + TASK-089 (pack) + TASK-090 (docs) = **PR #153**
(открыт, CI идёт). После мержа ФАЗА C код-полная. Остаток: owner-gated live-чек (нужен ключ) + TASK-091
(C7 граф) deferred. Следующая итерация = ФИНАЛИЗАЦИЯ: смержить #153, финальное резюме, обновить память, завершить цикл.

### Итог ФАЗЫ B (бриф: docs/research/twitter-source-research-brief.md)
- **Главное ограничение:** X API 2026 = legacy Basic/Pro ЗАКРЫТЫ → **pay-per-use $0.005/чтение,
  кап 2M/мес**. read-budget = центр дизайна (vs бесплатный TG MTProto). Дефолт-кадэнс Twitter
  **15 мин** (не 60с), `MAX_TWITTER_READS_PER_MONTH` + Redis-счётчик, no-op+алерт при превышении.
- **Env-ключ РЕШЁН:** `TWITTER_BEARER_TOKEN` (app-only Bearer). Метрики: like→reactions,
  retweet→forwards, impression→views, остальное extra. Лимиты планов — суммарные (осознанно).
- **Переиспользуем:** packs уже поддерживают `PackChannel(kind=TWITTER)`; collect_tick source-
  agnostic (новый Celery-таск НЕ нужен); pipeline/scorer платформо-независимы (C4 ≈ верификация).
- **Пререквизиты найдены:** storage `SourceKind` (channels.py) содержит ТОЛЬКО TELEGRAM → добавить
  TWITTER (+миграция?); watchlist handle-валидация Telegram-only → per-source `TWITTER_HANDLE_PATTERN`.
- **Нарезка C1-C7:** TASK-031 (refreshed) = ядро C1-C4 + пререквизиты; **TASK-089** C5 pack;
  **TASK-090** C6 docs; **TASK-091** C7 граф/independence (DEFERRED post-MVP, дорого по read-budget).
- C7 (collusion/independence-граф) = продуктовый моат, но post-MVP.

### Итог ФАЗЫ A (отчёт: cache/twitter-source-phase-a-report.md)
- Prod health ✅ GREEN: 9/9 сервисов, ingest свежий (18/2ч, newest 13:01, collect_tick ~60с),
  viral_score 93 шт ВСЕ>0 max 44.2, Redis 52/224M noeviction 0-evicted, session healthy=2,
  **0 auth-ошибок/24ч**, серт SAN оба домена.
- ⚠️ **T7 (`/v1/signals`+MCP) НЕ задеплоен** — премиса цикла неверна. Фича на не-смерженной
  `signal/t7-public-api-mcp` поверх не-смерженной `signal/t1..t6`; MCP=**stdio** (не HTTP/nginx);
  source=Empty (пусто). Автономно эпик НЕ мержу (product-surface, hard-to-reverse). → **TASK-088
  blocked owner-decision** + MANUAL-TODO §2-ter. ФАЗА A's «live MCP via nginx» неприменим к реальности.

### Заметки
- Doc-флипы task-087 (done) + ФАЗА A отчёт + TASK-088 — коммитятся PR'ом этой итерации.
- CI: красный «Dependency security scan» = ФРОНТЕНДНЫЙ esbuild-адвайзори (GHSA-gv7w-rqvm-qjhr, 3 high),
  НЕ required (mergeStateStatus UNSTABLE), к backend не относится; backend pip-audit чистый.
  Follow-up FZ-FE: бамп vite/esbuild отдельным frontend-PR (низкий приоритет).
- Прод доступен из песочницы: SSH `ssh -i ~/.ssh/id_ed25519 deploy@167.233.81.243` РАБОТАЕТ;
  HTTPS curl работает. docker swarm (имена `trendpulse_<svc>.1.<id>`); psql -U trendpulse -d trendpulse;
  таблица scores: ts-колонка `computed_at` (НЕ created_at).

## Прогресс по фазам
- [x] **ФАЗА 0** — AuthKeyDuplicated спам: классификация перманентных auth-ошибок + карантин
      мёртвого аккаунта из пула + алерт ровно один раз + PoolExhaustedError (тик не вешается).
      TASK-087. PR: #148. Owner-tail: перевыпуск мёртвых сессий (MANUAL-TODO §2-bis).
      Первопричина single-owner #3 — частично (PR #133 worker stop-first + память incident);
      остаток FZ0-2 (выделенный single-concurrency collector-воркер / disconnect-after-tick) —
      отдельная surgical-задача, НЕ блокирует (спам уже разорван карантином).
- [ ] **ФАЗА A** — prod health (сверить с памятью trendpulse-launch-state: 11/11, viral>0, Redis
      no-OOM, серт SAN, сессия healthy) + ЖИВОЙ end-to-end: HTTPS `/api/v1/signals` через nginx +
      реальная MCP-сессия через nginx (если SSE — `proxy_buffering off`, `proxy_read_timeout`).
      Чинить nginx.conf.template (+dev) как surgical-задачу. Без живого MCP-вызова A НЕ закрыта.
- [ ] **ФАЗА B** — research-бриф Twitter/X (ингест виральности, retweet/quote-граф, origin-tracing,
      collusion/ботнет, маппинг TG-механик на Twitter) в docs/ + набор task-doc'ов C1..C7.
- [ ] **ФАЗА C** — реализация Twitter-источника (C1 config → C2 collector → C3 registry+celery →
      C4 скоринг → C5 pack+seed «Crypto RU+EN» → C6 инструкция по данным → C7 граф/independence).
      Owner-blocked: живой Twitter-ключ (env). Код+моки до зелёного, живой чек — owner-tail.

## Сделанные задачи (PR)
- TASK-087 (ФАЗА 0) — карантин мёртвых TG-сессий + дедуп алерта. Branch
  `task/087-tg-authkey-quarantine`, baseline 9e85d1e. Verify: make test 830 passed, ci-fast зелёный,
  покрытие изм. модулей 91%. Review: 0 CRITICAL, HIGH (over-classification голого 401) исправлен.

## Открытые MANUAL-TODO (владелец)
- §2-bis (NEW): перевыпустить мёртвые TG-сессии по алерту «сессия #N мертва» (TASK-087).
- §8 (ранее): положить Twitter/X API-ключ в env (имя выберу в ФАЗЕ B, пропишу в config + .env.example).
- §2 (ранее): TG-пул ≥3 живых сессий.

## Дефолты/решения (фиксируются тут и в task-doc ## Discussion)
- Движок цикла: для ФАЗА 0 (well-scoped, prod-critical) выполнено напрямую (locate→TDD→verify→
  review-агент→ship) вместо тяжёлого skill-пайплайна — быстрее, контекст уже загружен. Для крупных
  фич ФАЗЫ C рассмотреть trendpulse-plan/executor skills.
- НЕ трогать `ops/ansible/vault/sensitive.vault.yml` (modified в рабочем дереве = owner live session).
  Коммитить ТОЛЬКО свои файлы явным `git add`.

## Следующий шаг (итерация 4 = ФАЗА C, старт)
1. Смержить PR ФАЗЫ B (research-бриф + task-031 refresh + 089/090/091 + index).
2. **TASK-031 (ядро Twitter-collector)** через plan→executor→verify, TDD:
   - config.py: `twitter_bearer_token` (optional, None-guard) + named const (кадэнс 15м,
     `MAX_TWITTER_READS_PER_MONTH`, max_results, backoff) + `.env.example`.
   - storage `SourceKind.TWITTER` (+ миграция если PG enum — ПРОВЕРИТЬ тип `Channel.source_kind`).
   - `collector/twitter/{__init__,client,mapper,reader,dedup}.py` по эталону telegram; rate-limit/
     read-budget внутри; `validate_ref` через `GET /2/users/by/username`; `read` через
     `GET /2/users/:id/tweets` (since_id). Тесты на замоканном API v2 (respx/fake), CI не дёргает X.
   - registry `register(SourceKind.TWITTER, _build_twitter_collector)`.
   - watchlist per-source `TWITTER_HANDLE_PATTERN` + валидация по source_kind.
   - C4 verify: Twitter RawPost → pipeline → viral_score (на моках; live owner-gated).
3. Затем TASK-089 (pack), TASK-090 (docs). TASK-091 — deferred.
4. Owner-gated живой чек ждёт `TWITTER_BEARER_TOKEN` (MANUAL-TODO). Код+моки до зелёного НЕ блокируются.

## (архив) Следующий шаг (итерация 3 = ФАЗА B) — ВЫПОЛНЕНО
1. Смержить PR этой итерации (doc-bookkeeping: task-087 done + ФАЗА A отчёт + TASK-088).
2. **ФАЗА B — research+план Twitter/X источника:**
   - Изучить код источников: `backend/src/collector/base.py` (SourceRef/SourceCollector/validate_ref),
     `registry.py`, `buffer.py`, `tasks.py`, эталон `collector/telegram/*`, фичу packs
     `backend/src/api/packs/*`. `SourceKind.TWITTER` уже в enum (ADR-001).
   - Доку: ADR-001 (source-abstraction), CODEMAPS коллектора/скоринга/packs, CONVENTIONS.
   - Research-бриф (docs/, рус): подходы к ингесту виральности из X, retweet/quote-граф,
     origin-tracing, collusion/ботнет, кросс-аккаунтная виральность; маппинг TG-механик на Twitter;
     что в MVP/что позже.
   - Дефолты (зафиксировать в task-doc): какой X API/тариф, имя env (X_BEARER_TOKEN vs
     TWITTER_BEARER_TOKEN — выбрать одно), модель данных/метрик, дедуп, rate-limit/backoff, маппинг.
   - Нарезать C1..C7 task-doc'и (config / collector / registry+celery / scoring / pack+seed /
     инструкция по данным / граф). НЕ ломать Telegram-путь и контракт SourceCollector.
3. Существующий старый `docs/tasks/task-031-twitter-source.md` (planned, Epic D) — свериться/
   переиспользовать как якорь, не плодить дубль.
