---
id: TASK-058
title: Боевая проверка платёжного пути — NOWPayments live, реальный IPN, raw-HMAC fallback, тестовый платёж
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-billing-live-verification"
tags: [launch, backend, billing, ops, security]
---

# TASK-058 — Боевая проверка платёжного пути (NOWPayments live)

> Биллинг написан и оттестирован моками/тест-секретом, но **реального IPN мы не видели**.
> Долг из learnings task-010: «NOWPayments подписывает sorted-key JSON — re-canonicalize
> рискует разойтись (ensure_ascii/float repr); нужен реальный IPN-сэмпл для byte-проверки».
> Если платёж сломается у ПЕРВОГО платящего — второго шанса не будет. Задача = код-страховка
> (raw-fallback + диагностика) + боевой прогон с реальным платежом и фиксацией сэмпла.

## Context

Сегодня (`backend/src/billing/gateway/nowpayments.py`): `verify_ipn()` парсит raw body
(`json.loads`) → `_canonical_json()` (`json.dumps(sort_keys=True, separators=(",",":"))`)
→ HMAC-SHA512 → `hmac.compare_digest` (constant-time, до доверия телу). Это соответствует
доке NOWPayments, но несёт риск re-canonicalization (float repr `10.0`→`10`, unicode
escaping) — расхождение = валидный платёж отвергается 401 и **деньги «теряются» молча**
для юзера. `process_ipn` (`billing/webhook.py`): `_ACTIVATING_STATUSES={"finished",
"confirmed"}` → `activate_or_extend`; идемпотентность по `status=="processed"`;
intermediate (`confirming`, `partially_paid`, `expired`) логируются без активации.
Секреты: `nowpayments_api_key`/`nowpayments_ipn_secret`/`nowpayments_base_url` (`config.py`;
пустой секрет → `BillingNotConfiguredError` → 503). Vault-ключи уже есть:
`vault_nowpayments_api_key`, `vault_nowpayments_ipn_secret`
(`ops/ansible/roles/env/templates/sensitive.env.j2`). Эндпоинт `POST /billing/ipn`
(unauthenticated, подпись = единственный гард) доступен как `/api/billing/ipn` через nginx.
Тесты: unit `test_billing_webhook.py` (мок gateway), integration `test_billing_ipn_route.py`
(реальный HMAC, но СВОЙ sorted-key JSON — самоисполняющееся пророчество, реальные байты
NOWPayments не проверены). Runbook: `docs/full-system-test.md` §B4 «живой NOWPayments
invoice (опц.)» — помечен опциональным, шагов недостаточно.

## Goal

После задачи: (1) verify_ipn устойчив к canonicalization-расхождению (raw-body fallback +
диагностическое событие); (2) на проде создан боевой NOWPayments-аккаунт, IPN callback
настроен, **реальный платёж прошёл полный цикл** waiting→…→finished → план активирован;
(3) redacted IPN-сэмпл зафиксирован и byte-проверка закрыта тестом по нему; (4) §B4
full-system-test.md превращён в пошаговый runbook. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Перейти на raw-байты целиком? → A: нет → Decision: **dual-verify**: primary —
  canonical sorted-key JSON (по доке NOWPayments, покрыт текущими тестами); fallback —
  HMAC по RAW-телу как пришло; матч любого = валидно. При «raw совпал, canonical нет» —
  `log_event("billing.ipn_canonical_mismatch", ...)` (длины + sha256-префиксы, БЕЗ тела
  и секретов) → собираем фактуру, платёж НЕ теряется. Оба пути — `compare_digest`.
- Q: Sandbox или сразу прод? → A: оба, по очереди → Decision: сначала
  `https://api-sandbox.nowpayments.io/v1` через существующий `nowpayments_base_url`
  (отдельный sandbox-аккаунт/ключи; IPN на dev-туннель ИЛИ сразу на прод-домен после 057)
  — прогон без денег; затем боевой платёж на проде. Никакого «тестового прайса» в коде —
  платим реальный Pro-инвойс ($29 после 049): деньги приходят на СВОЙ payout-кошелёк,
  себестоимость = комиссии (~1–3%).
- Q: Что фиксируем как сэмпл? → A: redacted → Decision: реальные IPN-байты с заменёнными
  значениями (payment_id/суммы оставить, order_id/адреса замаскировать) → fixture
  `backend/tests/fixtures/nowpayments_ipn_finished.json` (+ заметка о сырых байтах:
  записать exact bytes, не re-dump!) + тест «подпись настоящего сэмпла проходит canonical-
  путём» — если НЕ проходит, fallback-ветка обязана его принять (это и есть byte-проверка).
- Q: IPN callback URL — код или дашборд? → A: проверить на do → Decision: если
  `create_invoice` payload поддерживает `ipn_callback_url` — передавать из settings
  (`frontend_base_url`-производное или явный `nowpayments_ipn_callback_url`); иначе —
  one-time настройка в дашборде NOWPayments (Settings → IPN), шаг в runbook. Не блокирует.
- Q: `partially_paid` → деньги повисли? → A: известный seam → Decision: в ЭТОЙ задаче
  только проверяем, что статус логируется и идемпотентность не ломается; письмо «доплати»
  — TASK-048 (E4), не дублируем.
- Q: Когда гонять? → A: после 057 → Decision: финальный AC — на проде (HTTPS обязателен
  для IPN); sandbox-часть и код-страховка — сразу, не ждут 057.

## Scope
> **backend** (dual-verify + диагностика + fixture-тест) + **ops/runbook** (NOWPayments
> аккаунт, IPN URL, боевой прогон). Логику активации/идемпотентности НЕ трогаем.

- **Touch ONLY:**
  - `backend/src/billing/gateway/nowpayments.py` — `verify_ipn`: fallback HMAC по raw-body
    + `log_event("billing.ipn_canonical_mismatch", …)` (aggregate-only); порядок: canonical
    → raw → 401.
  - `backend/tests/unit/test_billing_webhook.py` — ветки dual-verify: canonical-only ok,
    raw-only ok (+mismatch-событие), оба мимо → IpnVerificationError.
  - `backend/tests/fixtures/nowpayments_ipn_finished.json` — **новый** (redacted боевой
    сэмпл, добавляется ПОСЛЕ live-прогона).
  - `backend/tests/integration/test_billing_ipn_route.py` — +тест на байтах fixture
    (точные bytes, не re-dump).
  - `docs/full-system-test.md` §B4 — расширить до runbook: создание аккаунта, ключи в
    vault (`ansible-vault edit`), IPN URL, sandbox-прогон, боевой платёж, что смотреть
    (logs/Sentry/`subscriptions.expires_at`), снятие сэмпла.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `process_ipn` статус-машину и идемпотентность (task-010 — работает),
  `activate_or_extend`, invoice-создание, rate-limit/nginx (`/billing/ipn` остаётся
  unauthenticated-by-design), `partially_paid`-обработку (TASK-048), цены (TASK-049).
- **Blast radius:** проверка подписи ЕДИНСТВЕННОГО гарда платёжного эндпоинта — любая
  ошибка = либо теряем платежи (false reject), либо дыра (false accept). Fallback строго
  ДОБАВЛЯЕТ принимаемое множество (raw тоже HMAC тем же секретом) — false accept не
  расширяется. Покрыть негативными тестами оба пути.

## Acceptance Criteria

- [ ] **AC1 — dual-verify (failing-test anchor).** Given тело, чья canonical-форма
  расходится с raw (float `10.0`, non-ascii) When подпись сделана по raw Then verify
  принимает и эмитит mismatch-событие; When подпись по canonical Then принимает молча;
  When подпись невалидна для обоих Then `IpnVerificationError` → 401 (unit).
- [ ] **AC2 — sandbox цикл.** Given sandbox-аккаунт + ключи When создан invoice и оплачен
  (sandbox-инструменты) Then реальные IPN-запросы приходят на стенд, подпись проходит,
  план активируется, replay идемпотентен (журнал прогона — в Details).
- [ ] **AC3 — боевой платёж (G2).** Given прод (после TASK-057) + боевые ключи в vault
  When владелец оплачивает Pro-инвойс реальной криптой Then последовательность IPN
  (waiting→confirming→finished) обработана, `users.plan=pro` + `subscriptions.expires_at`
  выставлены, `billing_payments.status=processed`, повторный finished-IPN — no-op;
  в логах НЕТ mismatch-события ЛИБО оно есть и fallback отработал (фиксируем фактуру).
- [ ] **AC4 — byte-fixture.** Redacted сэмпл реального IPN в fixtures; integration-тест
  гоняет его ТОЧНЫМИ байтами через `/billing/ipn` → 200. Долг task-010 закрыт.
- [ ] **AC5 — runbook.** §B4 проходится «с нуля» по шагам (свежая пара глаз/агент):
  от ключей до проверки активации; секреты нигде не печатаются (no_log-дисциплина).

## Plan

1. RED: unit-тесты dual-verify (AC1) → минимальная правка `verify_ipn` → GREEN.
2. Sandbox: аккаунт, ключи (локальный env/стенд), invoice → оплата → IPN на стенд
   (туннель или прод-стенд) — журнал в Details (AC2).
3. Runbook §B4 (по фактуре sandbox-прогона).
4. После TASK-057: боевые ключи в vault (`ansible-vault edit` + `make deploy` re-render),
   IPN URL на `https://<domain>/api/billing/ipn`, боевой платёж (AC3).
5. Снять redacted сэмпл (точные байты запроса) → fixture + integration-тест (AC4).
6. Verify G2 = AC3 сам по себе боевой; review + security 5.5 (платёжная поверхность).

## Invariants

- Подпись проверяется ДО любого доверия телу; оба пути — `hmac.compare_digest`.
- Пустой/отсутствующий секрет → 503 (как сейчас), НЕ «принять всё».
- Идемпотентность активации не ослабляется (ключ — terminal status, task-010).
- Секреты (ключи, suмы кошельков) — только vault; в логах/доке/fixture — redacted.
- Fallback не отключает canonical-путь (обратная совместимость с текущими тестами).

## Edge cases

- IPN пришёл ДО того, как наш POST /billing/invoice вернулся (гонка) → существующая
  обработка по order_id (инвойс уже в БД до редиректа) — проверить в sandbox.
- NOWPayments ретраит IPN при не-2xx → наш 401 на расхождении подписи вызовет ретраи —
  диагностическое событие позволит увидеть шторм; fallback делает сценарий маловероятным.
- `partially_paid` в боевом прогоне (недоплата сетевой комиссии) → статус логируется,
  активации нет — ожидаемо; доплата → finished. Письмо — TASK-048.
- Sandbox и прод подписывают одинаково, но суммы/валюты фиктивны → byte-fixture берём
  ТОЛЬКО с боевого IPN.
- Туннель для sandbox-IPN недоступен → допустимо гнать sandbox-этап против прод-стенда
  сразу после 057, до боевых ключей (порядок шагов в runbook).

## Test plan

- unit: dual-verify ветки (canonical/raw/none), mismatch-событие aggregate-only.
- integration: существующие IPN-тесты зелёные без правок (canonical-путь не тронут);
  новый byte-fixture тест (AC4).
- live: sandbox-цикл (AC2) + боевой платёж (AC3) — журнал в Details.
- security (5.5): ОБЯЗАТЕЛЬНО — платёжная поверхность: подпись-гард, отсутствие секретов
  в логах/фикстурах, 401/503-ветки, отсутствие user-controlled данных в log_event.

## Checkpoints

current_step: 3
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-billing-live-verification"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — sandbox + боевой платёж)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (REQUIRED — платёжная поверхность)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11. Закрывает долг task-010 (byte-HMAC) и «реальный платёжный путь не
проверен» из gap-анализа запуска. Код-часть (dual-verify) независима; боевая часть
зависит от TASK-057 (HTTPS) и TASK-049 (платим уже новую цену $29). Владелец-шаги:
NOWPayments аккаунт (KYC при необходимости), payout-кошелёк, ключи в vault, сам платёж.)
