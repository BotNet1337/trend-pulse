---
id: TASK-046
title: Реферальная программа USDT — ref_code, начисление при первой оплате реферала, страница «Пригласи»
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-e3-referral-program-usdt"
tags: [epic-e3, backend, frontend, billing]
---

# TASK-046 — Реферальная программа USDT (Epic E3)

> Привёл друга → получил USDT при его первой оплате. MVP: учёт в БД + выплата вручную.
> Touch-точки: users (ref_code, referred_by), register-путь (приём кода), billing webhook
> (начисление), страница «Пригласи». Независим от 044/045.

## Context

User-модель (`storage/models/users.py`): полей ref_code/referred_by НЕТ. Регистрация —
fastapi-users (`api/main.py` include) — приём ref-кода: query-param на фронте → передаётся
при register (кастомное поле в register-схеме fastapi-users ИЛИ отдельный POST /referral/claim
после регистрации — решить на locate, у fastapi-users есть UserCreate-расширение).
Оплата: `billing/webhook.py::process_ipn` — точка успеха `activate_or_extend(...)` в блоке
`event.status in _ACTIVATING_STATUSES` (~строка 84). BillingPayment имеет amount/currency.
Фронт: `frontend/src/pages/billing/billing.tsx`, features/account.

## Goal

(1) `users.ref_code` (уникальный, генерится при первом запросе GET /referral/me),
`users.referred_by` (nullable FK, ставится один раз при регистрации по ?ref=CODE).
(2) При ПЕРВОЙ успешной оплате реферала — строка `referral_rewards` (referrer_id,
referred_user_id UNIQUE, payment_id, amount = `referral_reward_usdt` константа, status=pending).
(3) GET /referral/me — код, ссылка, список наград (pending/paid). (4) Страница «Пригласи»
на фронте (ссылка + статус наград). Выплата вручную: оператор помечает paid
(`make referral-paid ID=…`). DoD = AC.

## Discussion
- Q: Процент от платежа или фикс? → Decision: **фикс в USDT** (`referral_reward_usdt`,
  default 10.0) — проще объяснить («приведи друга — получи $10») и проще ручная выплата.
  Процентная модель — после автоматизации выплат (не MVP).
- Q: Где вешать начисление? → Decision: в `process_ipn` СРАЗУ после `activate_or_extend`,
  в той же транзакции; условие «первая оплата» = нет processed-платежей юзера до этого
  (запрос по BillingPayment) И нет существующей награды (UNIQUE referred_user_id — двойная
  защита от replay/повторных IPN).
- Q: Как реферал привязывается? → Decision: `?ref=CODE` на лендинге/регистрации → фронт
  кладёт в localStorage → передаёт в register-запросе (расширение UserCreate) — привязка
  АТОМАРНА с созданием юзера (никаких «потом»: окно для абьюза и потерь). Self-referral
  (код == свой) — отказ. Код невалиден → регистрация ПРОХОДИТ, referred_by пуст (рефералка
  не должна ломать конверсию).
- Q: Выплата? → Decision: вручную (оператор шлёт USDT и помечает paid) — фиксируем в доке,
  автоматизация после $2k MRR.
- Q: Анти-абьюз минимум? → Decision: награда только при оплате (бесплатные рефералы ничего
  не дают), UNIQUE referred_user_id, self-referral отказ, log_event на каждое начисление.
  KYC/липовые карты — не наша поверхность (крипто-оплата).

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/0017_referrals.py` — **новая**: `users.ref_code`
    (varchar UNIQUE NULL), `users.referred_by` (FK NULL) + таблица `referral_rewards`
    (id, referrer_id FK, referred_user_id FK UNIQUE, payment_id, amount_usdt, status,
    created_at, paid_at NULL).
  - `backend/src/storage/models/users.py` + **новый** `referral_rewards.py`.
  - `backend/src/api/referral/` — **новый**: GET /referral/me (auth; lazy-генерация кода),
    схемы.
  - регистрация: расширение UserCreate/UserManager (fastapi-users) — приём ref-кода,
    резолв referrer, self-referral guard (точные файлы — на locate: api/auth/).
  - `backend/src/billing/webhook.py` — начисление после activate_or_extend (первая оплата).
  - `backend/src/config.py` — `referral_reward_usdt` (10.0).
  - `Makefile` — `referral-paid` target (оператор).
  - frontend: `frontend/src/pages/account/` или features/account — блок/страница «Пригласи»
    (ссылка с ref-кодом, список наград); лендинг/register — пронос ?ref → register-запрос.
  - OpenAPI dump + gen.types.
  - tests: `backend/tests/unit/referral/`, `backend/tests/integration/test_referral_flow.py`
    (**новые**); frontend unit на пронос ref.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** механика IPN-верификации (HMAC/replay — как есть), планы/цены,
  автоматические выплаты.
- **Blast radius:** register-путь (любая ошибка рефералки НЕ должна валить регистрацию —
  try/except + log), webhook-транзакция (+1 INSERT), users-миграция (nullable — безопасно).

## Acceptance Criteria
- [ ] **AC1 — привязка при регистрации (failing-test anchor).** Register с валидным ref →
  referred_by установлен; с невалидным/своим — регистрация ОК, referred_by NULL. RED.
- [ ] **AC2 — начисление при первой оплате.** IPN finished по рефералу без прежних оплат →
  referral_rewards(pending, amount=10.0); вторая оплата → новой награды НЕТ; повторный
  IPN того же платежа → НЕТ (replay-безопасно).
- [ ] **AC3 — GET /referral/me.** Авторизованный юзер получает код (генерится при первом
  запросе, стабилен), ссылку, награды; чужие награды не видны.
- [ ] **AC4 — операторская выплата.** make referral-paid ID → status=paid, paid_at; виден
  в /referral/me.
- [ ] **AC5 — фронт.** Страница «Пригласи» показывает ссылку; ?ref=CODE на регистрации
  доезжает до бэка (e2e или component-тест).
- [ ] **AC6 — G2.** Живой стек: register по ref-ссылке → мок-IPN оплаты → награда в БД и
  в /referral/me; make ci-fast + openapi-drift + frontend lint/tsc зелёные.

## Plan
1. **RED:** unit (код-генерация, self-guard, first-payment предикат) + integration
   (register-привязка, IPN-начисление, replay).
2. Миграция 0017 + модели + config.
3. Register-расширение + referral-роутер.
4. Webhook-начисление (try/except-изоляция).
5. Frontend: страница + пронос ref; gen-openapi/types.
6. GREEN + G2; tasks-index на ship.

## Invariants
- Рефералка НИКОГДА не ломает регистрацию и обработку платежа (изоляция ошибок + log).
- Одна награда на реферала (UNIQUE referred_user_id); начисление идемпотентно к IPN-replay.
- referred_by ставится один раз при регистрации, не переписывается.
- Выплата — только смена статуса оператором; никаких автодвижений денег в MVP.

## Edge cases
- Реферал удалил аккаунт (GDPR) до/после награды → каскад FK: до — награды не будет,
  после — награда остаётся у реферера (referred_user_id SET NULL? — решить на locate,
  склоняемся к сохранению награды с NULL-ссылкой).
- ref_code-коллизия при генерации → ретрай (короткий код из безопасного алфавита).
- Гонка двух IPN finished одного платежа → UNIQUE + транзакция.
- Юзер зарегался без ref, оплатил, потом «принёс» код → нет (привязка только при регистрации).

## Test plan
- **unit:** генерация кода, self-referral, first-payment предикат, reward-расчёт.
- **integration:** полный flow register(ref) → IPN → reward; replay; вторая оплата; /referral/me.
- **G2:** AC6 на живом стеке (IPN подписан тест-секретом, как в test_billing_ipn_route).
- **security (5.5):** ОБЯЗАТЕЛЬНО — register-input (ref-код = user input), enumeration
  ref-кодов (rate-limit), webhook-путь (replay уже покрыт HMAC — подтвердить).

## Checkpoints
current_step: 1
baseline_commit: ""
branch: "gsd/phase-e3-referral-program-usdt"
lock: ""
- [ ] 1 locate (scope + patterns + blast radius)
- [ ] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (REQUIRED — register input + billing-путь)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E3, независим от 044/045. Скоуп сознательно широкий (бэк+фронт):
при взятии в работу executor может развести на два PR — backend-механика и фронт-страница.
Ключевой инвариант: рефералка изолирована от регистрации и платёжного пути — любая её
ошибка деградирует тихо.)
