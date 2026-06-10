---
id: TASK-046
title: Реферальная программа USDT — ref_code, начисление при первой оплате реферала, страница «Пригласи»
status: done                # planned → in-progress → review → done
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
- [x] **AC1 — привязка при регистрации (failing-test anchor).** Register с валидным ref →
  referred_by установлен; с невалидным/своим — регистрация ОК, referred_by NULL. RED.
- [x] **AC2 — начисление при первой оплате.** IPN finished по рефералу без прежних оплат →
  referral_rewards(pending, amount=10.0); вторая оплата → новой награды НЕТ; повторный
  IPN того же платежа → НЕТ (replay-безопасно).
- [x] **AC3 — GET /referral/me.** Авторизованный юзер получает код (генерится при первом
  запросе, стабилен), ссылку, награды; чужие награды не видны.
- [x] **AC4 — операторская выплата.** make referral-paid ID → status=paid, paid_at; виден
  в /referral/me.
- [x] **AC5 — фронт.** Страница «Пригласи» показывает ссылку; ?ref=CODE на регистрации
  доезжает до бэка (e2e или component-тест).
- [x] **AC6 — G2.** Живой стек: register по ref-ссылке → мок-IPN оплаты → награда в БД и
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
current_step: done
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-e3-referral-program-usdt"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior; 1 CRITICAL найден и исправлен)
- [x] 5 review (adversarial — 2 CRITICAL (savepoint) + 1 HIGH найдены и исправлены)
- [x] 5.5 security (pass — параметризованный lookup, HMAC-путь, без enumeration, log-гигиена)
- [x] 6 ship (PR, squash-merge, CI зелёный)
- [x] 7 learnings (auto — docs/learnings.md 2026-06-11 TASK-046)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E3, независим от 044/045. Скоуп сознательно широкий (бэк+фронт):
при взятии в работу executor может развести на два PR — backend-механика и фронт-страница.
Ключевой инвариант: рефералка изолирована от регистрации и платёжного пути — любая её
ошибка деградирует тихо.)

### locate (2026-06-11, loop run)
- UserCreate: api/auth/schemas.py:15-16 (тонкий сабкласс BaseUserCreate) — добавить optional
  ref_code; UserManager.on_after_register: api/auth/users.py:87-100 — точка привязки
  (try/except, регистрацию не валит).
- users.py:57-85 — добавить ref_code (String UNIQUE NULL) + referred_by (FK users.id,
  **ON DELETE SET NULL** — награда переживает GDPR-удаление реферала; referrer_id в
  referral_rewards — CASCADE). Миграция 0017 (ALTER users + новая таблица).
- Webhook: billing/webhook.py:80-91 — после activate_or_extend (:84) в той же транзакции;
  идемпотентность IPN уже есть (status==processed guard :66-72). Предикат первой оплаты:
  нет processed-платежей юзера + NOT EXISTS reward (UNIQUE referred_user_id).
- Роутер-шаблон: api/account/delivery_config.py (current_user + get_db_session, extra=forbid).
- Код-генерация: secrets.token_urlsafe (паттерн api_keys/service.py) + ретрай на коллизию.
- Оператор: scripts/referral_paid.py по образцу case_mainstream.py + make-target.
- Frontend: features/auth/api.ts RegisterPayload + pages/auth/sign-up.tsx (?ref → localStorage
  → register); страница «Пригласи» рядом с billing/account; vitest-тест на пронос ref.
- IPN-тест шаблон: tests/integration/test_billing_ipn_route.py (HMAC-SHA512 подпись).

### do (2026-06-11, loop run)
- TDD RED→GREEN: 11 unit (referral service) + 9 integration (flow) + 7 vitest (ref-пронос);
  итог: ci-fast 565 unit, integration 164/10, eslint/tsc clean, 163 vitest.
- Привязка: UserCreate.ref_code (optional, max 32) → on_after_register._bind_referral
  (request.body JSON, свежая sync-сессия, write-once referred_by, try/except — регистрацию
  не валит). Невалидный код → регистрация ОК.
- Награда: в process_ipn после activate_or_extend, та же транзакция; предикат первой оплаты
  по processed-платежам ДО текущего; UNIQUE referred_user_id + replay-guard IPN.
- FK-решения: referred_user_id SET NULL (награда переживает GDPR-удаление реферала),
  referrer_id CASCADE. Гочча: User.oauth_accounts lazy='joined' → .unique() на запросах.
- Миграция 0017 применена; OpenAPI перегенерён; Makefile referral-paid (+скрипт).

### verify G2 + fix (2026-06-11, loop run)
- Живой стек: код lazy+стабилен; награда при первой оплате (подписанный IPN) + replay-guard +
  вторая оплата без новой награды; операторская выплата; изоляция между юзерами — PASS.
- **CRITICAL (найден G2, исправлен):** UserCreate.ref_code коллидировал с ORM-колонкой —
  fastapi-users create_update_dict() вставлял код рефера как СВОЙ ref_code нового юзера
  (UniqueViolation → 500 при реальной регистрации; 'NOPE' загрязнял колонку). Интеграционные
  тесты били в service-слой и этого не видели. FIX: поле переименовано в referrer_code +
  create_update_dict() override (pop перед INSERT) + 3 HTTP-path RED-теста через
  POST /auth/register + правка фронта (localStorage key, payload) + регенерация OpenAPI.
- Живая re-проверка после фикса: A→код; B с referrer_code=A → referred_by=A.id, ref_code NULL;
  C с 'NOPE' → 201 чисто.
- Гейты: ci-fast 565; integration 167/10; frontend lint/tsc/163 vitest; drift — только
  ожидаемые M-файлы дампа.
- LOW: referral_link строится от frontend_base_url (в проде = публичный домен) — ок;
  тест AC1 уровня сервиса дополнен HTTP-уровнем.

### review + security + fix-цикл #2 (2026-06-11, loop run)
- review CRITICAL×2: хук начисления на общей сессии IPN — `session.rollback()` при
  IntegrityError откатывал ВСЮ транзакцию (потеря активации плана при гонке двух IPN), а
  проглоченное не-IntegrityError исключение оставляло транзакцию aborted → 500 на flush.
  Ровно анти-паттерн savepoint из learnings TASK-038. FIX: весь блок начисления в
  `session.begin_nested()`; RED-тесты обоих сценариев падали до фикса (потеря processed /
  лишняя награда), зелёные после.
- review HIGH: `.one_or_none()` в предикате первой оплаты — MultipleResultsFound на 3-й
  оплате реферала. FIX: `.limit(1).first()` + тест 3-й оплаты.
- review MEDIUM: убраны все type:ignore (cast + mypy-override на модуль schemas;
  httpx.Response в тестах; user: User вместо object); `__import__('sqlalchemy')` →
  нормальные импорты; докстринг _bind_referral честен (отдельная sync-сессия, best-effort).
- security: pass (LOW: referred_user_id во /me — принято для MVP; INFO: entropy 48 бит — ок).
- Гейты: ci-fast 565; integration 170/10; frontend lint/tsc/163 vitest; referral flow 15/15.
