---
id: TASK-064
title: Фидбек 👍/👎 в вебе — кнопки на детальной странице алерта + optimistic update
status: review        # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: "task/064-alert-feedback-web-ui"
tags: [frontend, alerts, feedback, spa, backend-extension]
---

# TASK-064 — Фидбек 👍/👎 в вебе (alert feedback web UI)

> Кнопки 👍/👎 на `/alerts/:id` поверх существующего feedback-механизма TASK-042
> (HMAC-токены + UPSERT). Текущая оценка видна, повторный тап меняет её,
> optimistic update. Требует маленького backend-расширения: `AlertRead` не несёт
> ни verdict, ни токенов.

## Context

Backend-механика готова (TASK-042): `GET /api/v1/feedback/{token}` —
`backend/src/api/feedback/router.py:83-159`, неаутентифицированный эндпоинт,
токен = единственный bearer (`alerts/feedback_tokens.py:86-117`: HMAC-SHA256 от
`jwt_secret` с солью `b"feedback"`, payload `{a: alert_id, v: up|down, e: exp}`,
TTL `feedback_token_ttl_seconds`, дефолт 7д — `config.py:413`). UPSERT в
`alert_feedback` по constraint `uq_alert_feedback_alert_id`
(`feedback/router.py:129-144`), last-write-wins, идемпотентен. Ответ — HTML
(«Спасибо»), не JSON. Токены сейчас минтятся ТОЛЬКО при отправке Telegram-алерта
(`alerts/formatting.py:130-136`) — SPA их не получает.

Веб-витрина алерта: `frontend/src/pages/alerts/detail.tsx` (TASK-016/020),
данные через `useAlert(id)` (`frontend/src/features/alerts/queries.ts:54`) →
`GET /alerts/{alert_id}` → `AlertRead`
(`backend/src/api/alerts/schemas.py:20-31`: id/score/topic/first_seen/
channels_count/delivery_status — **ни feedback-состояния, ни токенов**).
Тип фронта — `components['schemas']['AlertRead']`
(`frontend/src/entities/alert/model.ts:10`), query key `alertQueryKey(id)`.

Паттерн мутаций — `features/packs/queries.ts` (useMutation + invalidate);
optimistic-update паттерна в кодовой базе ещё нет — этот таск вводит первый
(canonical TanStack `onMutate`/`onError` rollback).

## Goal

Юзер на `/alerts/:id` видит свою текущую оценку (👍 / 👎 / нет) и может поставить
или изменить её одним кликом; UI обновляется мгновенно (optimistic), при ошибке
откатывается. Telegram-кнопки продолжают работать без изменений (общий UPSERT —
последняя оценка побеждает). DoD = AC + vitest/e2e зелёные + drift-check.

## Discussion

- Q: `GET /alerts/{id}` отдаёт feedback-состояние или token? → A: нет (проверено:
  `AlertRead` `schemas.py:20-31`) → Decision: **маленькое backend-расширение** —
  три additive-поля в `AlertRead`: `feedback: "up" | "down" | null` (текущий
  verdict юзера из `alert_feedback`), `feedback_token_up: str | null`,
  `feedback_token_down: str | null` (минтятся на лету `sign_feedback_token` при
  сборке ответа). Это переиспользует ВЕСЬ существующий путь записи
  (`/feedback/{token}` + UPSERT + funnel-событие TASK-050) — новый
  авторизованный POST-эндпоинт был бы вторым write-path'ом с дублированием
  rate-limit/валидации.
- Q: токены в list-ответе (`GET /alerts`) тоже? → A: нет → Decision: поля
  additive с дефолтом `None`; сервис заполняет их ТОЛЬКО в detail
  (`get_alert`), list отдаёт `null` — не платим за HMAC×2 на каждый из 20 items
  страницы. Кнопки в списке алертов — вне scope (можно добрать отдельным таском,
  если кликстрим покажет потребность).
- Q: как SPA вызывает запись — ведь `/feedback/{token}` отвечает HTML? → A:
  статусом → Decision: `apiClient.get('/feedback/${token}')` , успех = HTTP 200,
  тело игнорируем. Менять response_class под JSON не нужно (Telegram-юзеры
  открывают тот же URL в браузере — HTML обязателен).
- Q: optimistic update или invalidate-after? → A: optimistic → Decision:
  `onMutate` пишет verdict в кэш `alertQueryKey(id)`, `onError` откатывает
  снапшот, `onSettled` инвалидирует — мгновенный отклик на тап (паттерн
  TanStack canonical). Токены при смене оценки НЕ протухают (UPSERT
  last-write-wins), повторный тап тем же токеном идемпотентен.
- Q: rate-limit `/feedback/{token}` (30/мин per-IP, unauthenticated) не помешает
  SPA? → A: нет → Decision: один юзер физически не делает 30 тапов/мин; 429
  обрабатываем как обычную ошибку (rollback + сообщение). Лимит не трогаем.
- Q: deps 042/016 — в main? → A: да (волна E смержена, PR #52-63); блокеров нет.
- Q: HTML-страницы `/feedback/{token}` на русском («Спасибо») — переводить на EN
  (продукт EN-only)? → A: вне Scope — `backend/src/api/feedback/router.py` в
  Do-NOT-touch списке этого таска → Decision: не трогаем здесь; EN-перевод HTML —
  отдельный микро-таск (см. Details). SPA тело ответа игнорирует (важен только
  статус), так что веб-флоу это не затрагивает.

## Scope

> Frontend + контролируемое backend-расширение читающего эндпоинта
> (3 поля в `AlertRead`, запись НЕ трогаем).

- **Touch ONLY:**
  - `backend/src/api/alerts/schemas.py` — `AlertRead`: `feedback: str | None = None`,
    `feedback_token_up: str | None = None`, `feedback_token_down: str | None = None`
    (+ docstring: заполняются только в detail).
  - `backend/src/api/alerts/service.py` — в detail-ветке: LEFT JOIN/запрос
    `alert_feedback` по `alert_id` (verdict smallint → "up"/"down" по маппингу
    `storage/models/alert_feedback.py` VERDICT_UP/VERDICT_DOWN) + минт двух
    токенов `sign_feedback_token(...)` с `settings.feedback_token_ttl_seconds`.
  - `backend/src/api/alerts/router.py` — только если сигнатура сервиса требует
    settings/прокидки (минимально).
  - `backend/tests/unit/` + `backend/tests/integration/` — тесты detail-ответа
    (см. Test plan).
  - `frontend/src/shared/api/openapi.json` + `gen.types.ts` — `make gen-openapi
    gen-types` (поля попадут в `AlertRead` автоматически; CI drift-check,
    `Makefile:242`).
  - `frontend/src/features/alerts/api.ts` — `sendFeedback(token: string)`
    (GET `/feedback/{token}`, ждём 200).
  - `frontend/src/features/alerts/queries.ts` — `useSendFeedback(alertId)` с
    optimistic update кэша `alertQueryKey(id)`.
  - `frontend/src/pages/alerts/detail.tsx` — блок 👍/👎 (две кнопки c
    `aria-pressed` по текущему verdict, disabled пока нет токенов/идёт мутация).
  - `frontend/tests/unit/alerts/alert-feedback.spec.ts(x)` — новый.
  - `frontend/tests/e2e/alerts.spec.ts` — сценарий фидбека (дополнение).
- **Do NOT touch:** `backend/src/api/feedback/router.py` (write-path, rate-limit,
  HTML-ответы — работают для Telegram); `alerts/feedback_tokens.py` (формат
  токена); `alerts/formatting.py` (Telegram-кнопки); список `pages/alerts/list.tsx`
  (кнопки в списке вне scope); адаптивный порог TASK-043 (читает `alert_feedback`
  — формат записи не меняется); `_bmad/**`, `.claude/**`.
- **Blast radius:** `AlertRead` — additive-поля c `None`-дефолтом: list-ответ
  (`AlertListResponse.items`) получает три `null`-поля — потребители фронта
  (`alert-card`, model) типобезопасно игнорируют; `extra="forbid"` не ломается
  (это про вход). Telegram-flow не затронут. `gen.types.ts` — общий файл,
  additive. Detail-эндпоинт получает +1 SELECT и +2 HMAC — пренебрежимо.

## Acceptance Criteria

- [ ] **AC1 — оценка ставится из веба.** Given юзер на `/alerts/:id` без оценки
  When кликает 👍 Then кнопка мгновенно становится активной (optimistic), And
  запрос `GET /api/v1/feedback/{token_up}` возвращает 200, And в
  `alert_feedback` появляется строка verdict=up (integration).
- [ ] **AC2 — текущая оценка видна и меняется.** Given юзер уже поставил 👍
  (из веба или из Telegram) When открывает `/alerts/:id` Then 👍 подсвечена
  (`feedback: "up"` в ответе detail); When кликает 👎 Then подсветка
  переключается, UPSERT обновляет ту же строку (last-write-wins).
- [ ] **AC3 — rollback при ошибке.** Given API отвечает ошибкой (сеть/400/429)
  When юзер кликает 👍 Then optimistic-состояние откатывается к прежнему verdict
  и показывается error-сообщение.
- [ ] **AC4 — list не утяжелён.** Given `GET /alerts` (list) Then элементы несут
  `feedback*`-поля как `null` (токены не минтятся в list-ветке — unit на сервис).
- [ ] **AC5 — Telegram-flow не сломан.** Существующие feedback-тесты TASK-042
  (token verify, UPSERT, rate-limit, 410) зелёные без правок поведения.
- [ ] **AC6 — G2.** `make ci` (включая openapi-drift-check) + vitest + e2e
  зелёные; ручная проверка на стеке: тап в SPA → строка в `alert_feedback`.

## Plan

1. Backend RED: unit/integration — `GET /alerts/{id}` содержит `feedback=null` и
   валидные токены (verify_feedback_token раскручивает их обратно в alert_id);
   после `GET /feedback/{token_up}` повторный detail отдаёт `feedback="up"`.
2. Backend GREEN: `schemas.py` (3 поля) → `service.py` (join verdict + минт
   токенов только в detail) — минимальный diff.
3. `make gen-openapi gen-types` — закоммитить дамп + типы.
4. `frontend/features/alerts/api.ts` + `queries.ts` — `sendFeedback` +
   `useSendFeedback` (onMutate снапшот → optimistic verdict; onError rollback;
   onSettled invalidate `alertQueryKey(id)`).
5. `pages/alerts/detail.tsx` — блок 👍/👎 рядом с status-бейджем: рендер по
   `alert.feedback`, `aria-pressed`, disabled при `feedback_token_* === null`.
6. Тесты frontend: unit (optimistic + rollback через мок-apiClient; рендер
   текущего verdict) + e2e (клик 👍 → кнопка активна → reload → подсветка
   сохранилась).
7. Verify (G2): `make ci`, e2e, живой тап на стеке + psql-проверка строки.

## Invariants

- **Один write-path фидбека** — `/feedback/{token}` + UPSERT по
  `uq_alert_feedback_alert_id`; веб и Telegram пишут одинаково, TASK-043
  (адаптивный порог) и funnel TASK-050 продолжают читать те же события/строки.
- `user_id` берётся из строки алерта на сервере (`feedback/router.py:125`), не из
  токена и не из клиента — токен чужого алерта бесполезен (cross-account защита
  сохраняется).
- Токены минтятся только в detail-ответе аутентифицированного владельца алерта
  (tenant-scoped `get_alert`, 404 на чужой id) — не появляются ни в list, ни в
  логах фронта.
- Optimistic-кэш всегда сходится с сервером: `onSettled` → invalidate (даже при
  успехе), расхождение живёт максимум один рефетч.
- Никаких новых магических чисел: TTL — существующий
  `feedback_token_ttl_seconds`.

## Edge cases

- Токен протух (страница открыта >7д) → 400 от `/feedback/{token}` → rollback +
  сообщение «Refresh the page to rate this alert» (рефетч detail выдаёт свежие
  токены).
- Алерт удалён retention'ом между загрузкой и тапом → 410 → rollback + то же
  сообщение (далее существующий 404-стейт страницы при рефетче).
- Двойной быстрый клик 👍👍 → мутация идемпотентна (UPSERT тем же verdict);
  кнопки disabled на время `isPending` — гонки нет.
- Клик 👍 при уже стоящем 👍 → отправляем всё равно (идемпотентно, дешевле, чем
  ветвление «снять оценку» — снятие оценки backend не поддерживает, вне scope).
- 429 rate-limit → AC3-ветка (rollback + сообщение).
- `feedback_token_up=null` при непустом алерте (минт упал/секрет пуст — graceful
  degradation TASK-042) → кнопки скрыты, страница работает.
- Mobile: кнопки ≥44px touch-target, в строке с бейджами — переносятся
  (`flex-wrap`).

## Test plan

- backend unit: маппинг verdict smallint→строка; list-ветка не минтит токены
  (AC4); токены в detail верифицируются `verify_feedback_token` и несут верный
  alert_id/verdict.
- backend integration: detail → токен → `GET /feedback/{token}` → повторный
  detail c `feedback="up"`; смена up→down; чужой алерт → 404 (не изменилось).
- frontend unit (vitest, паттерн `tests/unit/alerts/`): `useSendFeedback`
  optimistic + rollback (мок apiClient, QueryClient inline); рендер
  `aria-pressed` по `feedback`; кнопки скрыты при null-токенах.
- e2e (Playwright, `tests/e2e/alerts.spec.ts`): на засиженном алерте тап 👍 →
  активная кнопка → reload → подсветка сохранена. (Если сидинг алертов в e2e
  недоступен — зафиксировать как ручную G2-проверку, как в существующем
  alerts-спеке.)
- security: затрагивает auth-смежную поверхность (bearer-токены в JSON-ответе) →
  стадия 5.5 ОБЯЗАТЕЛЬНА: проверить, что токены не логируются, отдаются только
  владельцу, TTL/scope не расширены.

## Checkpoints

current_step: 7
baseline_commit: "a6b0594"
branch: "task/064-alert-feedback-web-ui"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + runtime + real behavior)
- [x] 5 review (auto, adversarial) — pass, 0 CRITICAL/HIGH, 3 LOW (см. Details)
- [x] 5.5 security (REQUIRED — feedback-токены в API-ответе) — approve, 0 findings
- [x] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11: веб-витрина к feedback-механике TASK-042. Решение —
переиспользовать token-write-path вместо нового POST-эндпоинта; backend-расширение
ограничено тремя additive-полями detail-ответа. Первый optimistic-update паттерн
в SPA — задокументировать в learnings как эталон.)

(do/verify 2026-06-11, ветка task/064-alert-feedback-web-ui от a6b0594:
- backend: `_VERDICT_INT_TO_STR`, `_current_verdict`, `_mint_feedback_tokens`
  (graceful degradation: пустой jwt_secret / падение минта → (None, None) +
  warning-лог без токена), проводка только в `get_alert`; router не менялся.
- frontend: `sendFeedback` (GET /feedback/{token}, тело-HTML игнорируется),
  `feedbackMutationOptions` вынесен из `useSendFeedback` для тестируемости без
  React-mount (в проекте нет @testing-library/react — конвенция соседних спеков);
  компонент `AlertFeedbackButtons` в detail.tsx (aria-pressed, min-h-11/min-w-11
  ≥44px, role="alert" EN-ошибка, скрыт при null-токенах).
- integration: в `client`-фикстуре test_alerts_api.py добавлен override
  `feedback_get_db_session` → общая committing-сессия, иначе write-path не видит
  незакоммиченные фикстуры (у него своя session-зависимость с commit()).
- e2e: сценарий зафиксирован как test.skip + ручной G2-runbook — в e2e нет
  сидинга delivered-алертов (та же констатация, что в существующем alerts.spec).
- verify G2: ruff/ruff-format/mypy зелёные; backend unit 614 passed (5 errors —
  предсуществующие integration-marked тесты TASK-043 в tests/unit, требуют
  compose-host `postgres`, к таску отношения не имеют); integration
  test_alerts_api+test_feedback_api 27/27 (4 новых TASK-064, 8 старых TASK-042 —
  AC5); vitest 228 passed (23 файла, в т.ч. 8 новых); eslint/tsc clean;
  gen-openapi/gen-types идемпотентны (drift-check пройдёт после коммита дампа).
  Real-behavior round-trip покрыт integration-тестом через TestClient на живом
  Postgres 15432 (tp064-pg): detail → token → GET /feedback/{token_up} → 200 →
  detail feedback="up" → token_down → feedback="down". Ручной тап на полном
  стеке (make up недоступен) — owner-шаг AC6.)

(review 2026-06-11, adversarial, свежий контекст: re-verify зелёный — ruff/
ruff-format/mypy clean, backend unit 614 passed, vitest 228 passed (23 файла),
eslint/tsc clean, `make gen-openapi gen-types` идемпотентен (diff не растёт —
дамп и типы от регена, не от руки). Дифф пройден по трём линзам против
Scope/AC/CONVENTIONS. CRITICAL/HIGH: нет. LOW (не блокируют, фиксация):
- L1 scope: `frontend/src/features/alerts/index.ts` не объявлен в Touch ONLY —
  barrel re-export новых символов, обязательная проводка, additive.
- L2 тесты: render-decision блок в `alert-feedback.spec.tsx` проверяет локальные
  pure-копии логики (shouldRenderFeedback/isUpPressed), а не JSX компонента —
  следствие отсутствия @testing-library/react (конвенция соседних спеков);
  JSX-регрессию словит только manual G2/e2e. Optimistic/rollback при этом
  тестируется на РЕАЛЬНОМ `feedbackMutationOptions` через MutationObserver.
- L3 типизация: `AlertRead.feedback: str | None` — свободная строка, не
  Literal["up","down"] (так в Scope); потребитель сравнивает `=== 'up'/'down'`,
  неизвестное значение деградирует в «нет подсветки» — безопасно.
Инварианты подтверждены: единый write-path (feedback/router.py не тронут),
токены только в detail tenant-scoped владельцу (404 на чужой id — integration),
list не минтит (unit + integration AC4), onSettled→invalidate сходимость кэша,
TTL — существующий `feedback_token_ttl_seconds`, токены не логируются.)
