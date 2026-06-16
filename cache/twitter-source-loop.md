# Twitter-source loop — ЛОГ ИТЕРАЦИЙ

## Итерация 1 — 2026-06-14 — ФАЗА 0 (AuthKeyDuplicated fix)
- Ориентация: прочитал loop-prompt, MANUAL-TODO, tasks-index, reader.py/account_pool.py/
  errors.py/client.py/pool_health.py/constants.py/tasks.py/registry.py + тест-конвенции.
- Root-cause подтверждён: `reader._read_one` алертит на non-flood resolve-ошибке, НО не выселяет
  аккаунт → пул каждый тик отдаёт ту же мёртвую сессию → спам. PR #133 уже закрыл deploy-overlap.
- TDD: написал `test_auth_quarantine.py` (AC1-AC6) первым → реализовал:
  `telegram/auth_errors.py` (классификатор), `account_pool.py` (quarantined-флаг, quarantine_current,
  PoolExhaustedError, quarantined_count, исключение из cooling/cooldown), `reader.py`
  (_quarantine_dead_account + классификация в обеих non-flood ветках), `errors.py`
  (PoolExhaustedError), `pool_health.py` (quarantined в aggregates), `tasks.py` (ловит PoolExhausted).
- Verify: `make test` 830 passed (0 fail), покрытие изменённых модулей 91%, ci-fast зелёный.
- Review (code-reviewer агент): 0 CRITICAL. HIGH — базовый `UnauthorizedError` мог ложно
  карантинить живой аккаунт на транзиентном 401 → УБРАЛ базовый класс (fail-safe), тесты обновлены.
- Ship: branch task/087-tg-authkey-quarantine, baseline 9e85d1e, PR #148 (open).
- Next: ФАЗА A (prod health + живой MCP/`/v1/signals` через nginx).

## Итерация 2 — 2026-06-14 — мердж ФАЗЫ 0 + ФАЗА A
- PR #148 (TASK-087): CI зелёный кроме «Dependency security scan» (фронтенд esbuild GHSA, не required,
  не относится к backend; backend pip-audit чистый). Backend job pass 4m41s. **Смержил squash → 9c77dd5**,
  ветку удалил. Doc-флипы task-087 → done.
- ФАЗА A: prod верифицирован из песочницы (SSH+HTTPS работают).
  **Health ✅ GREEN**: 9/9 сервисов, ingest свежий (18/2ч), viral_score 93 шт ВСЕ>0 max 44.2,
  Redis 52/224M noeviction 0-evicted, session healthy=2, 0 auth-ошибок/24ч, серт SAN оба домена.
  **T7 ⚠️ НЕ задеплоен** (премиса цикла неверна): `/api/v1/signals`=404; фича на не-смерженной
  `signal/t7-public-api-mcp` поверх не-смерженной `signal/t1..t6`; MCP=stdio (не HTTP/nginx);
  source=Empty. Автономно эпик не мержу → TASK-088 (blocked owner-decision) + MANUAL-TODO §2-ter +
  отчёт cache/twitter-source-phase-a-report.md.
- Next: ФАЗА B (research Twitter/X + нарезка C1-C7 task-doc'ов).

## Итерация 3 — 2026-06-14 — ФАЗА B (research + нарезка C1-C7)
- Изучил: collector/base.py, ADR-001, task-031 (уже детальный план C1-C3!), packs/data.py
  (PackChannel.kind УЖЕ есть), config.py (telegram-паттерн), tasks.py (collect_tick source-agnostic).
- Web research: X API 2026 = legacy Basic/Pro ЗАКРЫТЫ → pay-per-use $0.005/чтение кап 2M/мес
  → read-budget = центр дизайна. Bot-detection: co-retweet/rapid-retweet/account-age/co-hashtag.
- Найдены пререквизиты: storage SourceKind=только TELEGRAM; watchlist handle Telegram-only.
- Написал research-бриф docs/research/twitter-source-research-brief.md (главный артефакт ФАЗЫ B).
- Нарезка: TASK-031 refreshed (ядро C1-C4 + пререквизиты + X API реальность + env-ключ
  TWITTER_BEARER_TOKEN); TASK-089 (C5 pack); TASK-090 (C6 docs); TASK-091 (C7 граф, DEFERRED post-MVP).
- tasks-index + state + log обновлены. Коммит PR'ом (docs/planning-only).
- Next: ФАЗА C — старт TASK-031 (collector ядро) plan→executor→verify TDD; live owner-gated на ключ.

## Итерация 4 — 2026-06-14 — ФАЗА C, TASK-031 PR-A (collector ядро)
- Реализован collector/twitter (client/mapper/dedup/reader) + config (twitter_bearer_token) +
  constants (read-budget кадэнс15м/MAX_TWITTER_READS_PER_MONTH/429-cap) + registry register(TWITTER)
  + errors + .env.example (TWITTER_BEARER_TOKEN). TDD: test_twitter_collector.py 39 шт, 89% покрытие.
- read-budget: Redis месячный счётчик, при исчерпании stop+ops-алерт раз/мес; 429 backoff inline-cap,
  long-reset → skip ref; validate_ref никогда не пробрасывает; pipeline для INCRBY+EXPIRE.
- storage source_kind = native_enum=False VARCHAR без CHECK → миграция НЕ нужна (PR-B добавит enum
  значение + watchlist per-source handle).
- make test 867 passed; ci-fast зелёный. Review: 2 HIGH (non-429 рвала тик; malformed json) + 3 MEDIUM
  (бюджет per-month; атомарный счётчик; normalize_handle path/query) — все исправлены.
- registry-тест AC7 (TWITTER not registered) обновлён → теперь registered.
- Next: смержить PR-A; затем PR-B (storage SourceKind.TWITTER + watchlist handle) → 089 → 090.

## Итерация 4b — 2026-06-14 — PR-A смержен
- PR #152 backend CI зелёный (4m33s), смержен squash → main 7e90bff, ветка удалена.
  Фронт-esbuild dep-scan красный (не required, игнор). Collector ядро Twitter в main.
- Next (итерация 5): PR-B storage SourceKind.TWITTER + watchlist per-source handle → 089 → 090.

## Итерация 5 — 2026-06-14 — ФАЗА C PR-B + 089 + 090
- PR-B: storage SourceKind.TWITTER (миграция не нужна, подтверждено grep 0001 — native_enum=False
  без CHECK) + per-source TWITTER_HANDLE_PATTERN в watchlist (model_validator, telegram backward-compat).
- TASK-089: pack `crypto-twitter` (~43 RU+EN, PackChannel kind=TWITTER, bare-lowercase ≤15); live
  validate_ref owner-gated на ключ; мёртвые скипаются при чтении.
- TASK-090: docs/twitter-data-guide.md (рус) + MANUAL-TODO §8-bis (владельцу: X API доступ + TWITTER_BEARER_TOKEN).
- Тесты: test_watchlist_schemas (twitter accept/reject, telegram не сломан) + test_packs_catalog
  (per-kind формат). make test 880 passed; ci-fast зелёный. → PR #153 (открыт, CI идёт).
- ФАЗА C код-полная после мержа #153. TASK-091 deferred. Next: финализация цикла (резюме + память).

## Итерация 6 (в рамках 5) — 2026-06-14 — ФИНАЛИЗАЦИЯ
- PR #153 backend CI зелёный (4m43s), смержен squash → main 7d1e4cc. ФАЗА C код-полная.
- Память обновлена: trendpulse-twitter-source-loop.md + MEMORY.md индекс.
- ЦИКЛ ЗАВЕРШЁН. Финальное резюме выдано владельцу. ScheduleWakeup НЕ вызывается (loop окончен).

## Итерация 6 (scheduled-wakeup) — 2026-06-14 — NO-OP
- Финализация уже выполнена в пред. ходе (#153 merged 7d1e4cc, память + резюме готовы).
- Idempotent-проверка: #153 MERGED, открытых twitter-PR нет, память на месте, state=ЗАВЕРШЁН.
- Ничего не делаю. ScheduleWakeup НЕ вызывается. ЦИКЛ ОКОНЧАТЕЛЬНО ЗАВЕРШЁН.
