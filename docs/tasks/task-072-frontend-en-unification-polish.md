---
id: TASK-072
title: EN-унификация SPA + бренд Foresignal — перевод русских UI-строк, brand-alignment, корректный delete-account текст
status: planned            # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [frontend, copy, i18n, polish, spa]
---

# TASK-072 — Язык и полировка: EN-only SPA

> Продукт EN-only (решение зафиксировано ниже): переводим ВСЕ русские
> user-facing строки SPA на английский (онбординг, паки, тренды) и чиним
> delete-account диалог, говорящий про «workspaces/posts» из чужого проекта.
> i18n-фреймворк НЕ вводим.
>
> Плюс brand-alignment (запрос владельца 2026-06-11): публичное имя платформы —
> **Foresignal** (домен foresignal.biz). Все user-facing упоминания «TrendPulse»
> в SPA, на landing и в API docs (OpenAPI title) → «Foresignal». «TrendPulse»
> остаётся только во внутренних идентификаторах/доках/коде.

## Context

SPA выросла кусками: страницы Epic C/D (auth, watchlists, alerts, billing,
settings) написаны на EN, а свежие фичи волны Е (онбординг TASK-039, паки
TASK-038, тренды TASK-044-смежные) — на русском. Лендинг полностью EN,
ЦА международная (крипто-трейдеры/SMM), тарифы в USD. Смешение языков в одном
флоу (EN sign-up → RU onboarding → EN dashboard c RU-блоком «Наборы») выглядит
как недоделка и бьёт по конверсии — это launch-polish перед платным трафиком.

Инвентарь кириллицы в `frontend/src` (grep `[А-Яа-яЁё]`, user-facing):
- `frontend/src/pages/onboarding/page.tsx` — весь онбординг: «Добро пожаловать!»
  (`:69`), «Выберите тему…» (`:71`), «Шаг 1/2/3…» (`:78,114,134`), CTA
  «Подключить набор/Подключение…/Подключено!» (`:154-162`), «Пропустить»
  (`:170`), ошибки (`:53`), aria-метки (`:86`).
- `frontend/src/features/packs/packs-block.tsx` — блок «Наборы каналов» на
  watchlists-странице: feedback-строки (`:33,36,49`), «N каналов» (`:63`),
  кнопки «Подключить/Отключить…» (`:73-85`), заголовок/описание (`:110-113`),
  загрузка/ошибка/пусто (`:117-129`), aria (`:117,133`).
- `frontend/src/features/packs/error-message.ts` — «Лимит паков…», «Набор не
  найден.», «Что-то пошло не так…» (`:22-29`).
- `frontend/src/features/trending/trending-list.tsx` — «Вирусность» (`:45`),
  «Загрузка…» (`:60-61`), ошибка (`:69`), «Собираем сигналы…» (`:78-83`),
  empty (`:92`), aria (`:98`).
- Тесты, ассертящие русские строки: `frontend/tests/unit/packs/packs-api.spec.ts:21-64`.
- НЕ user-facing (не переводим): русские комментарии в коде/тестах (язык
  коммуникации проекта — русский, docs/CLAUDE.md), `shared/api/gen.types.ts`
  (автоген из backend-docstrings — правится только regen'ом, вне scope).

Отдельный копирайт-баг: `frontend/src/features/account/delete/ui/
delete-account-dialog.tsx:63-72` — описание удаления аккаунта говорит про
«workspaces» и «posts» (скопировано из другого проекта); call-site передаёт
заглушки `ownedWorkspacesCount={0}` / `ownedPostsCount={0}`
(`features/account/settings/ui/account-settings-view.tsx:206-213`). У TrendPulse
сущности — watchlists / alerts / subscription.

`console.warn` в landing root (`landing/src/app/root.tsx:15`,
`landing/src/pages/legal/legal-page.tsx:22`) — осознанно ВНЕ scope: это
landing-приложение, а таск frontend-SPA; warn'ы диагностические, не user-facing.

## Goal

В SPA не остаётся ни одной русской user-facing строки (UI-тексты, aria-метки,
сообщения об ошибках); delete-account диалог описывает реальные последствия для
TrendPulse-аккаунта. `grep -rn '[А-Яа-яЁё]' frontend/src --include='*.tsx'
--include='*.ts'` находит только комментарии и `gen.types.ts`. DoD = AC.

## Discussion

- Q: EN-only или i18n-фреймворк (react-i18next и т.п.)? → A: EN-only →
  Decision: **продукт EN-only, i18n НЕ вводим.** Rationale: ЦА международная,
  лендинг и 80% SPA уже EN, цены в USD; i18n-слой = постоянный налог на каждую
  строку (ключи, файлы переводов, ревью) без единого запроса на локализацию.
  Если появится RU/иной рынок — отдельная задача, строки к тому моменту уже
  будут собраны в компонентах единообразно. Решение durable — кандидат в ADR
  при learnings.
- Q: переводить ли русские комментарии в коде? → A: нет → Decision: комментарии
  и test-описания — внутренняя коммуникация (проект ведётся на русском,
  docs/CLAUDE.md «Communicate in Russian»); scope = только user-facing строки.
- Q: delete-account — какой текст? → A: честный TrendPulse-текст → Decision:
  «Removes your account, your watchlists, alerts history and subscription.
  This cannot be undone.» + убрать мёртвые props `ownedWorkspacesCount`/
  `ownedPostsCount` (оба call-site-значения — заглушки `0`, конкретики они не
  дают; меньше API компонента — меньше лжи). Сверить формулировку с реальным
  каскадом удаления backend'а (TASK-033 GDPR-export/delete) на do-стадии.
- Q: `console.warn` в landing — чинить заодно? → A: нет → Decision: вне scope
  (другое приложение, не SPA); зафиксировано в Context, чтобы не потерялось.
- Q: тон/глоссарий перевода? → A: согласовать с существующим EN-слоем →
  Decision: «pack» (не «set»; уже в лендинге и backend-слаг `packs`),
  «channel(s)», «Connect pack / Disconnect», «Skip», «Something went wrong.
  Please try again.» (дословно как в `shared/api/client.ts:19`
  GENERIC_ERROR_MESSAGE — единый голос ошибок), «Loading…» (как в
  `pages/alerts/detail.tsx:79`).
- Q: deps 039? → A: онбординг TASK-039 в main — переводим его строки, не
  переделывая flow. Блокеров нет.
- Q: бренд — TrendPulse или Foresignal? → A: запрос владельца (2026-06-11):
  единое публичное имя **Foresignal** (по домену foresignal.biz) → Decision:
  все user-facing вхождения «TrendPulse» (SPA: titles/headers/meta/футер;
  landing: hero/footer/meta/legal-страницы; backend: `FastAPI(title=…)` и
  описание OpenAPI → видимы в `/docs`) заменить на «Foresignal». Внутренние
  имена (пакеты, slugs, env-префиксы `TRENDPULSE_*`, docs/, имена репо/compose)
  НЕ трогаем — это не user-facing и blast radius несоразмерен. Инвентарь
  вхождений снять grep'ом `-i 'trendpulse'` по `frontend/src`, `landing/src`,
  `backend/src/main.py`(+app factory) на do-стадии. Правка backend-title меняет
  OpenAPI-дамп → `make gen-openapi gen-types` в этой же ветке.

## Scope

> Только строки и один компонентный API (props delete-диалога). Ни логики, ни
> роутинга, ни backend.

- **Touch ONLY:**
  - `frontend/src/pages/onboarding/page.tsx` — все RU-строки → EN (заголовок,
    шаги, CTA, ошибки, aria-метки).
  - `frontend/src/features/packs/packs-block.tsx` — RU-строки → EN (включая
    aria-label'ы и feedback-сообщения мутаций).
  - `frontend/src/features/packs/error-message.ts` — RU-сообщения → EN
    (generic-ветку выровнять на `GENERIC_ERROR_MESSAGE`-формулировку).
  - `frontend/src/features/trending/trending-list.tsx` — RU-строки → EN
    («Вирусность» → «Virality», «Собираем сигналы…» → «Collecting signals…»,
    empty/error/aria).
  - `frontend/src/features/account/delete/ui/delete-account-dialog.tsx` —
    description → TrendPulse-текст; удалить props `ownedWorkspacesCount`/
    `ownedPostsCount` (`:19-22,30-32,66-68`).
  - `frontend/src/features/account/settings/ui/account-settings-view.tsx:206-213`
    — убрать передачу удалённых props.
  - `frontend/tests/unit/packs/packs-api.spec.ts` — ассерты на новые EN-строки.
  - `frontend/tests/unit/**` — прочие падающие из-за строк ассерты (найти на
    do-стадии прогоном vitest; ожидаемо onboarding/trending-спеки).
  - `frontend/tests/e2e/**` — селекторы по русскому тексту, если есть
    (проверить grep'ом; smoke/alerts используют EN-селекторы).
  - **Brand-alignment (Foresignal):** user-facing «TrendPulse» → «Foresignal» в
    `frontend/src/**` (titles, headers, meta, delete-account копия),
    `frontend/index.html` (`<title>`), `landing/src/**` + `landing/index.html`
    (hero/footer/meta/legal), backend app factory (`FastAPI(title=…,
    description=…)`) → затем `make gen-openapi gen-types` (дамп и `gen.types.ts`
    обновляются ТОЛЬКО регеном); тесты, ассертящие старое имя.
- **Do NOT touch:** ручные правки `frontend/src/shared/api/gen.types.ts`
  (обновляется только regen'ом); русские комментарии в src/tests; внутренние
  идентификаторы `trendpulse` (env-префиксы, slugs, пакеты, compose, docs/);
  `console.warn` в `landing/src/app/root.tsx:15` (диагностика, не user-facing);
  backend HTML-страницы `/feedback/{token}`
  (`backend/src/api/feedback/router.py:53-69` — RU «Спасибо»; Telegram-поверхность,
  кандидат на EN в связке с TASK-064, не здесь); flow онбординга/паков/трендов
  (только текст); `_bmad/**`, `.claude/**`.
- **Blast radius:** чисто презентационный: разметка и логика не меняются;
  единственное API-изменение — props `DeleteAccountDialogProps` (один call-site,
  `account-settings-view.tsx:206`). Риск — тесты/e2e, завязанные на строки:
  закрываются в том же diff'е.

## Acceptance Criteria

- [ ] **AC1 — кириллицы в UI нет.** Given собранный SPA When
  `grep -rn '[А-Яа-яЁё]' frontend/src --include='*.ts' --include='*.tsx'`
  Then совпадения только в комментариях и `shared/api/gen.types.ts` (ни одного
  в JSX-тексте, строковых литералах UI, aria-атрибутах).
- [ ] **AC2 — онбординг EN.** Given новый юзер (0 watchlists) When AuthGuard
  приводит его на `/onboarding` Then весь флоу (welcome, шаги 1-3, CTA, skip,
  ошибки) — на английском, флоу работает как до правки (пак подключается).
- [ ] **AC3 — паки/тренды EN.** Given юзер на `/watchlists` Then блок паков
  (заголовок, кнопки, лимит-ошибка 402, empty/loading) — EN; Given showcase
  warming-up Then плейсхолдер «Collecting signals…»-семантики — EN.
- [ ] **AC4 — delete-account честный.** Given юзер открывает Danger zone →
  Delete account Then описание упоминает account/watchlists/alerts/subscription
  и НЕ упоминает workspaces/posts; подтверждение по email и сам делит работают
  как прежде.
- [ ] **AC5 — G2.** vitest (включая обновлённые packs-ассерты) + eslint + tsc +
  e2e зелёные; визуальный проход onboarding → watchlists → settings без
  смешения языков.
- [ ] **AC6 — бренд Foresignal.** Given собранные SPA и landing When
  `grep -rni 'trendpulse' frontend/src frontend/index.html landing/src
  landing/index.html` Then ноль user-facing совпадений (комментарии/внутренние
  идентификаторы допустимы); Given открыт `/docs` (Swagger UI) Then title
  OpenAPI = «Foresignal…», «TrendPulse» в title/description отсутствует.

## Plan

1. RED: обновить ассерты `tests/unit/packs/packs-api.spec.ts` на EN-строки +
   добавить unit-ассерт на отсутствие workspaces-текста в delete-диалоге →
   падают.
2. `features/packs/error-message.ts` + `packs-block.tsx` — перевод (генерик-текст
   = `GENERIC_ERROR_MESSAGE`-формулировка) → GREEN packs-тесты.
3. `pages/onboarding/page.tsx` + `features/trending/trending-list.tsx` — перевод
   строк и aria; прогнать vitest целиком, добить падающие ассерты в
   onboarding/trending-спеках.
4. `delete-account-dialog.tsx` — новый description, удалить props; поправить
   call-site `account-settings-view.tsx`; сверить текст с реальным каскадом
   удаления (TASK-033).
5. Brand-alignment: grep-инвентарь `-i trendpulse` (frontend/src, index.html,
   landing/src, landing/index.html, backend app factory) → замена user-facing
   вхождений на «Foresignal» → `make gen-openapi gen-types` (title в дампе) →
   обновить ассерты тестов на имя.
6. Финальный grep AC1 + grep AC6 + e2e-прогон + визуальный проход (G2).

## Invariants

- Поведение/флоу не меняются: ни одного нового условия, хука, запроса — только
  строковые литералы и сигнатура props delete-диалога.
- Единый голос ошибок: generic-ошибки дословно совпадают с
  `GENERIC_ERROR_MESSAGE` (`shared/api/client.ts:19`) — не плодим вариации.
- aria-метки переведены СИНХРОННО с видимым текстом (скринридер не остаётся
  русским при EN-экране).
- Терминология совпадает с лендингом и тарифной копией TASK-049 («packs»,
  «channels», «Trader») — без новых синонимов.
- `gen.types.ts` в diff не попадает (маркер, что автоген не трогали руками).

## Edge cases

- Интерполированные строки с числами («N каналов», «N каналов пропущено») →
  EN-плюрализация ручная (`channel/channels` по count) — без i18n-библиотек,
  паттерн уже есть в delete-диалоге (`workspace/workspaces`-тернарник).
- Ошибка 402 c `detail` от backend (EN-текст «packs limit reached…») внутри
  RU-обёртки → новая EN-обёртка не должна дублировать смысл detail'а
  («Pack limit reached: {detail}» → проверить читабельность).
- e2e/unit, ищущие текст регэкспом без учёта регистра — после перевода прогнать
  ВЕСЬ vitest/playwright, а не только packs (скрытые завязки на строки).
- Длина EN-строк vs RU в кнопках онбординга (CTA с названием пака) — проверить
  переполнение на mobile (truncate уже стоит на title-элементах packs-блока).
- Юзеры середины флоу в момент деплоя — нет persisted-строк: все тексты
  рендерятся из бандла, миграций не требуется.

## Test plan

- unit (vitest): обновлённые `tests/unit/packs/packs-api.spec.ts` (EN-ассерты);
  существующие onboarding/trending-спеки (правки ассертов по факту прогона);
  новый ассерт: delete-диалог рендерит watchlists/subscription-копию и не
  содержит «workspace».
- e2e (Playwright): существующие `smoke/auth/watchlists/billing-account`-спеки —
  зелёные (EN-селекторы); онбординг-флоу при наличии спека — обновить тексты.
- Регрессия-сетка: финальный grep AC1 — встраивается в G2-чеклист verify-стадии
  (не в CI-hook: кириллица в комментариях легальна).
- security: не требуется (только строки; подтвердить skip на review).

## Checkpoints

current_step: 3
baseline_commit: "c390c4c"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (skip ожидаем — только копирайт)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11: launch-polish перед платным трафиком — EN-only решение
зафиксировано (кандидат в ADR), i18n-фреймворк осознанно не вводим. Инвентарь
кириллицы снят grep'ом на baseline c390c4c: onboarding/packs/trending + ассерты
в packs-тестах; delete-account «workspaces» — наследие чужого проекта,
call-site передаёт заглушки 0/0.)

(2026-06-11, запрос владельца: scope расширен brand-alignment'ом — публичное
имя платформы «Foresignal» (= домен foresignal.biz) в SPA, landing и API docs
(OpenAPI title/description); внутренние идентификаторы trendpulse не трогаем.
Blast radius: + landing-строки и backend app-title с regen'ом OpenAPI; логики
по-прежнему ноль.)
