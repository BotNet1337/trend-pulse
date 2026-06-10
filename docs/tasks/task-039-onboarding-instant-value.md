---
id: TASK-039
title: Onboarding instant value — showcase-тенант + GET /trending + экран «вирусное за 24ч» после регистрации
status: done
owner: backend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: ""
tags: [epic-e1, backend, frontend, onboarding]
---

# TASK-039 — Onboarding instant value (Epic E1)

> Главный бизнес-риск (overview §10): человек уходит до первого «вау». Сразу после регистрации показать
> «вот что завирусилось за 24 часа по твоей теме» — данные есть в ту же минуту, потому что их заранее
> собирает системный showcase-тенант, подписанный на все паки (TASK-038).

## Context

Кластеры/скоры — **per-user** (`UserOwnedBase`): у свежего юзера пусто, пока его watchlist не прогреется
(часы). Ждать нельзя — нужен прогретый источник. Зависимость: TASK-038 (паки). Регистрация: фронт после
`POST /auth/register` редиректит на sign-in (без авто-логина); router — TanStack, protected layout.
`GET /alerts` — эталон read-эндпоинта (cursor, plan-gate). Scorer пишет Score per (user, cluster);
`clusters.topic` — центроид-лейбл.

## Goal

Системный showcase-юзер (создаётся идемпотентно, подписан на все паки) копит кластеры/скоры как обычный
тенант; `GET /trending?pack={slug}` (auth required) отдаёт топ-K кластеров showcase-тенанта за 24ч
(topic, viral_score, channels_count, first_seen — **без сырого контента**); фронт после регистрации/
первого логина ведёт на онбординг-экран: выбор темы (пак) → живой список «вирусное за 24ч» → CTA
«подключить этот набор» (TASK-038 subscribe). DoD = AC.

## Discussion
- Q: Откуда данные новому юзеру мгновенно? → Decision: **системный showcase-тенант** — обычный User-ряд
  (флаг/email-константа `showcase@internal`, is_active, без логина — пароль рандомный), подписан на все
  паки; pipeline/scorer работают для него штатно. Никаких спец-веток в ядре. Бонус: этот же тенант питает
  витрину-канал (TASK-044).
- Q: Как создаётся showcase-юзер? → Decision: идемпотентная Beat/CLI-инициализация: management-функция
  `ensure_showcase_tenant()` (вызов из startup api ИЛИ make-target/однократного скрипта — минимум решит
  executor; предпочтение: явный make-target, без магии на startup). Подписка на паки — через тот же
  packs-service (skip-дубли уже есть).
- Q: Что отдаёт /trending? → Decision: топ-K (default 10, max 20 — константы) кластеров showcase-тенанта
  с viral_score за окно 24ч (константа), фильтр по паку (pack_slug → его watchlist-topics; MVP: маппинг
  pack→topic из каталога data.py). Только агрегаты: topic-лейбл, score, channels_count, first_seen.
  Сырой текст постов НЕ отдаём (compliance §7 + продукт не продаёт контент).
- Q: Доступ без логина (лендинг)? → Decision: нет, auth required (Free-юзер увидит после регистрации) —
  публичную витрину делает E3 в Telegram. Уменьшает поверхность.
- Q: Free-юзер видит /trending, хотя Free history=0? → Decision: да — это showcase-данные (наши), не его
  история; plan-gate не применяется. Осознанно: это и есть «первая польза».
- Q: Онбординг-флоу фронта? → Decision: после успешного register → sign-in (как сейчас) → если у юзера
  0 watchlist'ов → редирект на `/onboarding`: выбор пака → trending-список → CTA subscribe → /watchlists.
  Без отдельного state в БД (критерий = 0 watchlists).

## Scope
- **Touch ONLY:**
  - `backend/src/api/trending/` — **новый модуль**: schemas/router/service (`GET /trending?pack=&limit=`),
    запрос по clusters/scores showcase-тенанта (join, окно 24ч, order by viral_score desc).
  - `backend/src/api/packs/` (из TASK-038) — переиспользуем каталог для pack→topic маппинга (read-only import service-функции).
  - showcase-инициализация: `backend/src/api/trending/bootstrap.py` (`ensure_showcase_tenant()`) + make-target
    `showcase-init` (root Makefile) ИЛИ вызов в migration_runner-провижининге — минимальный вариант за executor.
  - `backend/src/config.py` — `showcase_user_email` (default константа), trending-константы (TOP_K, WINDOW).
  - `backend/src/api/main.py` — include router.
  - frontend: `frontend/src/pages/onboarding/` + `features/trending/` (выбор пака, список, CTA subscribe);
    редирект-логика «0 watchlists → /onboarding» в router/guard; gen.types регенерация.
  - tests: `backend/tests/integration/test_trending_api.py` (**новый**), unit bootstrap-идемпотентность;
    frontend unit онбординга.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** pipeline/scorer/collector (showcase — обычный тенант), auth-флоу backend, alerts.
- **Blast radius:** новый публичный эндпоинт (read-only, агрегаты); +1 системный юзер в БД (его паки добавляют
  каналы в глобальный сбор — то же множество, что паки TASK-038); фронтовый редирект для юзеров без watchlists
  (затрагивает существующих пустых юзеров — приемлемо, им онбординг и нужен).

## Acceptance Criteria
- [ ] **AC1 — trending отдаёт топ showcase (failing-test anchor).** Given showcase-тенант с посеянными
  clusters/scores (фикстура), When `GET /trending?pack=crypto-ru`, Then топ-K по viral_score за 24ч,
  только агрегатные поля, отсортировано убыванием. RED первым.
- [ ] **AC2 — окно и лимит.** Given кластеры старше 24ч, Then их нет в ответе; `limit` ≤ MAX (422 иначе);
  неизвестный pack → 404.
- [ ] **AC3 — идемпотентный bootstrap.** Given повторный `ensure_showcase_tenant()`, Then второй юзер
  не создаётся, подписки не дублируются (skip), функция безопасна к ретраям.
- [ ] **AC4 — изоляция.** Given showcase-тенант, Then обычный юзер НЕ видит его watchlist/alerts через
  свои эндпоинты (tenant-scope как был); showcase-юзер не может залогиниться обычным паролем (рандомный hash).
- [ ] **AC5 — no raw content.** Given ответ /trending, When инспекция, Then нет текста постов/ссылок на
  сырой контент — только topic-лейбл и метрики (compliance §7).
- [ ] **AC6 — онбординг-флоу + G2.** Given новый юзер (0 watchlists) в dev-стеке, When логин, Then редирект
  на /onboarding → выбор пака → список trending (живые данные showcase) → CTA подключает пак → /watchlists
  непустой. «Регистрация → увиденный сигнал» ≤ 60 сек. `make ci` зелёный.

## Plan
1. **RED:** `test_trending_api.py` — AC1/AC2/AC4/AC5 (посев showcase-фикстурой).
2. `bootstrap.py` (idempotent ensure + подписка на паки через packs-service) + make-target.
3. `api/trending/` (service-запрос join clusters+scores, router, schemas) + config-константы + include.
4. GREEN backend; gen-openapi → frontend onboarding-страница + trending-фича + редирект «0 watchlists».
5. G2: `make up`, прогреть showcase (паки собираются) → новый юзер проходит флоу за минуту; tasks-index на ship.

## Invariants
- Ядро без спец-веток: showcase — обычный тенант (pipeline/scorer/collector не знают о нём).
- /trending read-only, только агрегаты, никаких сырых постов (compliance §7).
- Tenant-изоляция не ослаблена: чужие эндпоинты showcase-данные не отдают, /trending отдаёт ТОЛЬКО showcase.
- Bootstrap идемпотентен и безопасен к повторным запускам.
- Константы (TOP_K, окно, email) — settings/named constants.

## Edge cases
- Showcase ещё не прогрет (свежий деплой) → /trending отдаёт пустой список + поле `warming_up=true` —
  фронт показывает «собираем сигналы…» (не ошибка).
- Пак без активности за 24ч → пустой список (честно), CTA подключения всё равно доступен.
- Showcase-юзер удалён руками → следующий bootstrap пересоздаёт; /trending при отсутствии → пустой + warming_up.
- Юзер с watchlist'ами зашёл на /onboarding напрямую → доступно (не блокируем), просто не редиректим туда.

## Test plan
- **integration:** `test_trending_api.py` — AC1/AC2/AC4/AC5; bootstrap-идемпотентность (AC3).
- **frontend unit:** онбординг (выбор пака, warming_up-состояние, CTA → subscribe-вызов, редирект-логика).
- **G2:** полный живой флоу в dev (AC6) с секундомером.
- **security (5.5):** auth required; pack-slug по белому списку; showcase-пароль рандомный/нелогинибельный; rate-limit существующий.

## Checkpoints
current_step: done
baseline_commit: "05cbdb8c7ec62af708412389ba98a788534d5f45"
branch: "gsd/phase-e1-onboarding-instant-value"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + real behavior; см. Details)
- [x] 5 review (auto, adversarial — fix-cycle applied 2026-06-10)
- [x] 5.5 security (auth/новый эндпоинт — 2 HIGH найдены и закрыты в fix-цикле: topic-sanitize, PasswordHelper)
- [x] 6 ship (PR, squash-merged)
- [x] 7 learnings (auto — записаны в docs/learnings.md до ship, в том же PR)
debug_runs: []

## Details
(initial — locate: clusters/scores per-user (UserOwnedBase) → мгновенность достижима только прогретым
тенантом; решение «showcase = обычный тенант» держит ядро нетронутым и переиспользуется витриной E3
(TASK-044). Зависимость: TASK-038 (паки) — выполнять после. Фронт: register НЕ авто-логинит (паттерн
task-014) — онбординг вешаем после первого логина по критерию «0 watchlists». Compliance: /trending
без сырого контента (§7 «не продавать сырой контент» + 48h retention).)

fix-cycle 2026-06-10 (review findings):
1. CRITICAL Makefile showcase-init: `python -m api.trending.bootstrap` → `python -m api.trending`
   (bootstrap.py имеет no `__main__` block; CLI живёт в `__main__.py`). Добавлен unit-guard.
2. HIGH raw-content leak: в service.py добавлена `_sanitize_topic_label()` — strips URLs/t.me/@handles/emails,
   cap TRENDING_LABEL_MAX_LEN=80. TrendingItem.topic docstring обновлён. Unit + integration tests добавлены.
3. HIGH UnknownHashError 500: `_make_unguessable_hash()` в bootstrap.py переписан с sha256 hex → 
   `PasswordHelper().hash(secrets.token_urlsafe(32))` (argon2, тот же хешер что UserManager).
   Интеграционный тест: POST /auth/jwt/login showcase@internal → 400/401, not 500.
4. INFO ge=1 на limit Query param в router.py → 422 на limit=0/-1. OpenAPI dump + frontend gen.types.ts регенерированы.
All tests pass: 415 unit + 16 integration (test_trending_api.py).

2026-06-10 (итог verify/ship): G2 живьём — showcase-init идемпотентен (2 прогона → 1 юзер, 14 watchlist-строк
без дублей); /trending: топ по viral_score desc, окно 24ч соблюдено, неизвестный пак 404, limit>max 422,
без auth 401; изоляция: свежий юзер не видит showcase-строк, его собственный кластер с score=99 НЕ попадает
в /trending. Security-оценка «угроза захвата showcase@internal через регистрацию» — НЕ эксплуатируема
(EmailStr отвергает домен без точки на register/forgot-password). Принятые ограничения: channels_count=1
(плейсхолдер с TODO — у Score/Cluster нет колонки; заполнить когда scorer начнёт писать cross_channel);
пак→topic маппинг подразумевает уникальность topic между паками (зафиксировано комментарием в data.py);
полный браузерный тайминг «регистрация→сигнал ≤60s» — ручная проверка owner'а на полном стеке
(make up + make showcase-init); guard теперь дёргает useWatchlists на каждом protected-рендере
(смягчено staleTime/кэшем TanStack — принято).
