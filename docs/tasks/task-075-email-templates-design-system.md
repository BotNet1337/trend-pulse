---
id: TASK-075
title: Email-шаблоны — унификация под Aurora-дизайн-систему + ребренд Foresignal (G2), переиспользование токенов TASK-074 инлайн
status: planned          # planned → in-progress → review → done
owner: frontend
created: 2026-06-12
updated: 2026-06-12
baseline_commit: "af5885a"
branch: ""
deps: [TASK-074]
tags: [frontend, design-system, email, templates, rebrand, react-email]
---

# TASK-075 — Email-шаблоны под Aurora-дизайн-систему + ребренд Foresignal

> 9 react-email шаблонов и их общие компоненты приводятся к Aurora-дизайн-
> системе (визуальная цель — `designs/trendPulse/variants/templates/*.html`)
> и ребрендятся «TrendPulse» → «Foresignal» (аудит G2). Email не умеет внешний
> CSS — поэтому переиспользуем ЗНАЧЕНИЯ токенов, канонизированных в TASK-074
> (`landing/src/app/app.css`), **инлайн** (inline-стили, 600px-таблицы,
> bulletproof-кнопки). Только презентация + бренд-строки; транзакционная
> логика, пропсы, unsubscribe/compliance — без изменений.

## Context

Письма — `templates/` (react-email: `@react-email/components` +
`@react-email/render`, fastify-сервер рендера). Общие компоненты:
`templates/src/components/{layout,brand-header,footer,button}.tsx`. 9 шаблонов:
- auth: `welcome`, `verify-email`, `reset-password`, `email-change-requested`,
  `email-changed`;
- lifecycle: `weekly-digest`, `win-back`;
- billing: `renewal`, `underpaid`.

**Дельта дизайна (baseline `af5885a`):**
- Текущие компоненты используют **плоскую violet-палитру**, НЕ согласованную с
  лендингом: `brand-header.tsx` mark-gradient `#6366F1→#8B5CF6→#A78BFA`,
  name-color `#0F172A`; `button.tsx` `#6366F1→#8B5CF6`, pill-radius 100px;
  `layout.tsx` body-gradient `#EDE9FE→#F5F3FF→#FAF5FF→#F0F4FF`, card белый
  `#FFFFFF` radius 24px maxWidth 560px; `footer.tsx` muted `#CBD5E1`.
- Дизайн-моки `variants/templates/*.html` задают **Aurora-палитру** (blue→
  violet→cyan), согласованную с landing-primary `#2563eb`:
  - brand-gradient `linear-gradient(135deg,#2563eb 0%,#7c3aed 100%)`;
  - accent-gradient `linear-gradient(90deg,#2563eb 0%,#7c3aed 50%,#22d3ee 100%)`;
  - тёмный хедер-бенд `linear-gradient(135deg,#070b1d 0%,#0c1228 50%,#1b2350 100%)`;
  - cyan-акцент `#22d3ee`, текст `#0f172a`/`#475569`/`#94a3b8`, светлые
    карточки `#ffffff`/`#eef1fb`/`#eef2ff`.
  То есть письма надо перевести с «плоского violet» на «Aurora blue+violet+cyan»,
  выровненную на landing-primary `#2563eb`.

**Дельта бренда (G2, hardcoded «TrendPulse»):**
- `components/brand-header.tsx:66` (`<Text>TrendPulse</Text>`),
  `components/footer.tsx:48,60` («TrendPulse · …», «© 2026 TrendPulse»).
- `templates/auth/welcome.tsx:64,71`, `verify-email.tsx:45,51`,
  `reset-password.tsx:55`, `email-change-requested.tsx:60,66`,
  `email-changed.tsx:60`; `billing/renewal.tsx:70`.
- **Уже Foresignal** (частичный ребренд): `lifecycle/weekly-digest.tsx`,
  `lifecycle/win-back.tsx` — бренд в проде сейчас **смешан**.
- Централизованного `BRAND_NAME` в `templates/` НЕТ (`src/config.ts` пуст,
  бренд-строки литеральные).

**Контракт токенов с TASK-074:** канонические значения дизайн-системы живут в
`landing/src/app/app.css @theme` + reference-комментарий. Письма НЕ умеют
внешний CSS → берут ТЕ ЖЕ значения и хардкодят инлайн. Email-мок вводит
дополнительные email-only декоративные значения (accent-/header-градиенты, cyan
`#22d3ee`) поверх базового landing-primary `#2563eb` — это допустимое
расширение «для письма», базовый primary/текст/border синхронны с TASK-074.

> deps: **TASK-074** — нужны канонизированные значения токенов (landing-primary
> `#2563eb`, текст/border/card обеих контекстов) как источник истины для
> инлайн-значений писем.

## Goal

9 писем визуально соответствуют мокам `variants/templates/*.html` (Aurora
blue+violet+cyan), email-safe (600px таблицы, инлайн-стили, bulletproof-кнопки,
unsubscribe/compliance-строки сохранены); ноль user-facing «TrendPulse» (бренд
единообразно «Foresignal» через единый `BRAND_NAME`-источник); базовые значения
(primary/текст/border) совпадают с канонизированными токенами TASK-074. Пропсы,
транзакционная логика, рендер-сервер — без изменений. `build`+`lint` зелёные,
все письма рендерятся. DoD = AC.

## Discussion

- Q: как переиспользовать токены лендинга в email (внешний CSS невозможен)? →
  A: **инлайн-значения из единого источника** → Decision: создать
  `templates/src/components/tokens.ts` — TS-константы с ЗНАЧЕНИЯМИ,
  синхронизированными с TASK-074 `app.css` reference-блоком (brand `#2563eb`,
  текст `#0f172a`/`#475569`/`#94a3b8`, border, card-фоны) + email-only
  декоративные (accent-/header-градиенты, cyan `#22d3ee`). Компоненты/шаблоны
  импортируют константы вместо разбросанных hex-литералов. Email-safe сохраняем:
  значения попадают в inline-`style`, не в `<link>`/`<style>`-классы. Контракт:
  при изменении базового токена в TASK-074 — синхронная правка `tokens.ts`
  (комментарий-ссылка в обе стороны).
- Q: насколько 1:1 с email-моками? → A: визуальный паритет, email-safe-first →
  Decision: цель — соответствие мокам `variants/templates/*.html` в email-
  клиентах; при конфликте «пиксель мока» vs «email-safe рендер» (Outlook/Gmail)
  приоритет — **email-safe** (таблицы 600px, инлайн, bulletproof VML-кнопки,
  без неподдерживаемых градиентов там, где они ломаются — fallback solid-цвет).
  react-email уже даёт bulletproof-обвязку; сохраняем `safeHref` (XSS-гард).
- Q: dark-only / тёмные письма? → A: **светлые письма** → Decision: email-мок —
  светлая карточка на светлом фоне с тёмным брендовым хедер-бендом (НЕ dark-
  theme письмо). Большинство email-клиентов не поддерживают `prefers-color-
  scheme` надёжно → письма остаются светлыми (как и текущие и моки). Тёмный
  хедер-бенд `#070b1d…` — декоративный элемент, не тема.
- Q: единый источник бренда в письмах? → A: `BRAND_NAME`-константа →
  Decision: ввести `BRAND_NAME = 'Foresignal'` в `tokens.ts` (или
  `components/brand.ts`); заменить ВСЕ литералы «TrendPulse» на неё (header,
  footer, previewText, body-копия). Снизит риск повторного дрейфа бренда
  (сейчас прод смешан: lifecycle=Foresignal, auth/billing=TrendPulse).
- Q: трогаем ли копию писем (тексты, шаги, subject)? → A: только бренд-токен →
  Decision: контент verbatim; меняем ТОЛЬКО вхождение имени бренда
  «TrendPulse»→«Foresignal» и презентацию (стили). Структура previewText,
  шаги welcome, compliance/unsubscribe-строки, billing-суммы — без изменений.
- Q: tagline «Viral content detector» — оставить? → A: да → Decision: tagline —
  это копия, не бренд; verbatim. Меняем только «TrendPulse»→«Foresignal».
- Q: unsubscribe/compliance (TASK-069) — трогаем? → A: нет → Decision:
  `footer.tsx` unsubscribe-ветка и compliance-формулировки сохраняются 1:1;
  меняем только бренд-литерал и стили. Транзакционные письма по-прежнему без
  `unsubscribeUrl` (пропс опционален) — поведение неизменно.
- Q: pixel-почта Outlook/градиенты? → A: graceful fallback → Decision: каждому
  градиенту — `backgroundColor` solid-fallback (паттерн уже есть в текущих
  компонентах: `backgroundColor` + `background:linear-gradient`); Outlook
  возьмёт solid, современные клиенты — градиент.

## Scope

> Только презентация (инлайн-стили) + бренд-литерал. Ни пропсов, ни
> транзакционной логики, ни рендер-сервера, ни backend-вызовов.

- **Touch ONLY:**
  - **NEW** `templates/src/components/tokens.ts` — `BRAND_NAME` + значения
    дизайн-системы (синхронны с TASK-074 `app.css` reference) + email-only
    декоративные (accent/header-градиенты, cyan). Единственный источник hex.
  - `templates/src/components/layout.tsx` — body/card-стили под мок (фон,
    радиус, тень, maxWidth=600px email-safe), из `tokens.ts`.
  - `templates/src/components/brand-header.tsx` — Aurora brand-gradient,
    «TrendPulse»→`BRAND_NAME`, mark/name/tagline-стили из `tokens.ts`.
  - `templates/src/components/footer.tsx` — «TrendPulse»→`BRAND_NAME` (`:48,60`),
    muted-стили из `tokens.ts`; unsubscribe/compliance-логику и текст НЕ трогать.
  - `templates/src/components/button.tsx` — Aurora button-gradient + solid-
    fallback из `tokens.ts`; `safeHref` сохранить как есть.
  - 9 шаблонов `templates/src/templates/{auth,lifecycle,billing}/*.tsx` —
    (a) «TrendPulse»→`BRAND_NAME` в previewText/копии (auth+billing; lifecycle
    уже Foresignal — проверить); (b) выровнять локальные inline-стили
    (heading/body/muted/link hex) на `tokens.ts`. Структуру/копию НЕ менять.
  - Тесты/снапшоты рендера, если падают из-за бренда/стилей (прогон на do-стадии).
- **Do NOT touch:**
  - Пропсы шаблонов и их сигнатуры (`WelcomeEmailProps`, `unsubscribeUrl?`,
    billing-суммы, …) — API писем неизменно.
  - Транзакционная логика и рендер-сервер: `templates/server/*`
    (`registry.ts`, `handlers/*`, `server.factory.ts`, `config.ts`).
  - Копия писем: subject-семантика previewText (кроме бренд-слова), шаги
    welcome, compliance/retention-строки, unsubscribe-формулировка (TASK-069),
    tagline «Viral content detector».
  - `safeHref` XSS-гард (`button.tsx`) — поведение сохранить.
  - Backend-вызовы рендера (`api/auth/users.py`, `billing/*`) — вне templates,
    не в scope (бренд в backend-subject — отдельный follow-up из TASK-072
    Details).
  - `_bmad/**`, `.claude/**`, `tasks-index.md`.
- **Blast radius:** презентация + один бренд-литерал, вынесенный в константу.
  Логика рендера и пропсы неизменны. Риск: (1) email-клиент-рендер (Outlook/
  Gmail) при смене градиентов — закрывается solid-fallback и проверкой
  рендера; (2) рассинхрон `tokens.ts` с TASK-074 — закрывается комментарием-
  контрактом и тем, что базовые значения берутся из `app.css` reference;
  (3) пропущенный «TrendPulse» — закрывается grep AC.

## Acceptance Criteria

- [ ] **AC1 — визуальное соответствие email-мокам.** Given отрендеренные 9
  писем When сравнить с `variants/templates/*.html` Then каждое визуально
  соответствует моку (Aurora blue+violet+cyan: brand-gradient `#2563eb→#7c3aed`,
  accent/cyan, тёмный хедер-бенд, светлые карточки), с поправкой на email-safe-
  рендер.
- [ ] **AC2 — единый источник токенов, синхронный с TASK-074.** Given
  `templates/src/components/tokens.ts` Then базовые значения (brand `#2563eb`,
  текст/border/card) совпадают с reference-блоком `landing/src/app/app.css`
  (TASK-074); компоненты/шаблоны импортируют константы, hex-литералы не
  разбросаны по файлам.
- [ ] **AC3 — нет user-facing TrendPulse.** Given templates When
  `grep -rn 'TrendPulse' templates/src` Then ноль совпадений в user-facing
  (header/footer/previewText/копия); бренд = «Foresignal» через `BRAND_NAME`.
- [ ] **AC4 — email-safe сохранён.** Given каждое письмо Then таблицы ≤600px,
  все стили инлайн (нет внешнего CSS/классов), кнопки bulletproof с solid-
  fallback под градиентом, `safeHref` активен; письма рендерятся в
  `@react-email/render` без ошибок.
- [ ] **AC5 — unsubscribe/compliance/пропсы неизменны.** Given lifecycle-письма
  (welcome/weekly-digest/win-back) с `unsubscribeUrl` Then unsubscribe-ссылка и
  её формулировка (TASK-069) рендерятся 1:1; транзакционные письма без
  `unsubscribeUrl` — футер как прежде; ни одна пропс-сигнатура не изменена.
- [ ] **AC6 — копия verbatim.** Given diff Then изменены только бренд-слово
  «TrendPulse»→«Foresignal» и inline-стили; шаги welcome, billing-суммы,
  subject-семантика, tagline — без изменений.
- [ ] **AC7 — build/lint зелёные.** `npm run build` (tsc) + `lint` в
  `templates/` зелёные; все 9 шаблонов рендерятся (smoke через сервер/registry).

## Plan

1. RED: добавить тест — рендер каждого письма не содержит «TrendPulse» и
   содержит «Foresignal» в header/footer (через `@react-email/render` →
   HTML-строка) → падает на текущих auth/billing-шаблонах.
2. `tokens.ts`: `BRAND_NAME='Foresignal'` + значения дизайн-системы (синхронно
   с TASK-074 `app.css` reference) + email-only декоративные → база для всех.
3. Общие компоненты: `layout`/`brand-header`/`footer`/`button` — стили из
   `tokens.ts`, brand-gradient/Aurora, «TrendPulse»→`BRAND_NAME` → GREEN
   бренд-тест для header/footer.
4. 9 шаблонов: «TrendPulse»→`BRAND_NAME` в previewText/копии (auth+billing;
   lifecycle сверить); локальные hex → `tokens.ts`. Прогнать рендер всех.
5. `npm run build` + `lint`; добить падающие снапшоты/ассерты.
6. Verify: grep AC3, email-safe-чек (600px/инлайн/bulletproof, AC4), сверка
   значений `tokens.ts` ↔ `app.css` (AC2), рендер 9 писем vs моки (AC1),
   unsubscribe-проверка (AC5).

## Invariants

- Только презентация + бренд-литерал: ни одной правки пропсов, транзакционной
  логики, рендер-сервера, backend-вызова.
- Копия verbatim: тексты, шаги, billing-суммы, subject-семантика, tagline,
  compliance/unsubscribe-формулировки — байт-в-байт; меняется лишь слово
  «TrendPulse»→«Foresignal».
- Email-safe: ≤600px таблицы, инлайн-стили (никакого внешнего CSS — письма его
  не умеют), bulletproof-кнопки с solid-fallback под градиентом, `safeHref`
  XSS-гард активен, unsubscribe/compliance (TASK-069) сохранены.
- **Контракт токенов с TASK-074:** базовые значения (brand/текст/border/card) в
  `tokens.ts` = reference-блок `landing/src/app/app.css`; email-only
  декоративные (accent/header-градиенты, cyan) — допустимое расширение поверх.
  Изменение базового токена в TASK-074 → синхронная правка `tokens.ts`
  (взаимные комментарии-ссылки).
- Бренд единообразно через `BRAND_NAME` — ноль литералов «TrendPulse» в
  user-facing.

## Edge cases

- Outlook (Word-движок) не рендерит CSS-градиенты → каждому градиенту solid
  `backgroundColor`-fallback (паттерн уже в текущих компонентах); проверить
  brand-header mark, button, header-бенд.
- Gmail обрезает письма >102 КБ и режет некоторые стили — держать HTML
  компактным, инлайн без дублей (вынос в `tokens.ts` помогает).
- previewText с интерполяцией (`Welcome to ${BRAND}, ${userName}`) — следить,
  что замена бренда не ломает шаблонную строку.
- lifecycle уже частично «Foresignal» — не задвоить ребренд и не пропустить
  остаточные литералы; grep по ВСЕМ 9 + 4 компонентам.
- Тёмный хедер-бенд `#070b1d` под светлым логотипом-текстом — проверить
  контраст brand-name на тёмном фоне (если мок кладёт имя на бенд).
- cyan `#22d3ee` в accent-градиенте — низкий контраст как текст; использовать
  только как декор/границу, не как текст-на-белом (AA).
- `@react-email/render` версия — убедиться, что инлайн-стиль-объекты
  (camelCase) корректно сериализуются после рефактора на `tokens.ts`.

## Test plan

- unit/render: тест на каждое из 9 писем — HTML от `@react-email/render`
  содержит «Foresignal», не содержит «TrendPulse» (header+footer+тело);
  unsubscribe-ссылка присутствует при `unsubscribeUrl` и отсутствует без него.
- email-safe-чек (verify-стадия, ручной): таблицы ≤600px, нет `<link>`/
  `<style class>`, кнопки bulletproof, solid-fallback под градиентами,
  `safeHref` коллапсит non-http → `#`.
- Визуальная сверка (verify): рендер 9 писем (dev-сервер templates) vs
  `variants/templates/*.html` — это AC1.
- Контракт-сверка: значения base-токенов `tokens.ts` == reference-блок
  `landing/src/app/app.css` (AC2) — ручная диф-проверка на do/verify.
- security: проверить, что `safeHref` сохранён и url-пропсы по-прежнему через
  него проходят (review-чек); иначе skip.

## Checkpoints

current_step: 3
baseline_commit: "af5885a"
branch: ""
lock: ""
- [x] 1 locate (scope + дельта палитры/бренда + контракт с TASK-074)
- [x] 2 plan (G1 — презентация+бренд-литерал, deps TASK-074)
- [ ] 3 do (TDD: бренд-рендер-тест RED → tokens.ts → компоненты → 9 шаблонов)
- [ ] 4 verify (G2 — build+lint; рендер 9 писем; email-safe-чек; grep AC3;
      сверка tokens.ts↔app.css; unsubscribe AC5)
- [ ] 5 review (adversarial: Outlook-fallback, контраст на бенде/cyan,
      контракт токенов, verbatim-копия, safeHref сохранён)
- [ ] 5.5 security (safeHref XSS-гард активен; url-пропсы через него; иначе skip)
- [ ] 6 ship (PR из ветки — оркестратор; после TASK-074)
- [ ] 7 learnings (docs/learnings.md: email≠внешний CSS → инлайн-значения из
      единого tokens.ts; G2 ребренд; прод-бренд был смешан lifecycle/auth)
debug_runs: []

## Details

(planned 2026-06-12, baseline `af5885a`, deps TASK-074. Locate-факты:
- Текущие письма — плоский violet (`#6366F1→#8B5CF6→#A78BFA`), НЕ согласован с
  landing-primary. Email-моки `variants/templates/*.html` — Aurora blue+violet+
  cyan: brand `linear-gradient(135deg,#2563eb 0%,#7c3aed 100%)`, accent
  `#2563eb→#7c3aed→#22d3ee`, тёмный хедер-бенд `#070b1d→#0c1228→#1b2350`,
  cyan `#22d3ee`, текст `#0f172a`/`#475569`/`#94a3b8`. `#2563eb` = landing-primary
  → база синхронизируется с TASK-074.
- G2-ребренд: «TrendPulse» hardcoded в `brand-header.tsx:66`, `footer.tsx:48,60`
  и auth/billing-шаблонах (welcome/verify-email/reset-password/email-change-
  requested/email-changed/renewal). lifecycle (weekly-digest/win-back) УЖЕ
  Foresignal → прод-бренд писем смешан. Централизованного BRAND_NAME нет
  (`src/config.ts` пуст) → вводим `tokens.ts` с `BRAND_NAME`.
- Контракт с TASK-074: email не умеет внешний CSS → переиспользуем ЗНАЧЕНИЯ
  токенов (из `app.css` reference) инлайн через `tokens.ts`; email-only декор
  (accent/header-градиенты, cyan) — расширение поверх базы.
- Светлые письма (не dark-theme): тёмный хедер-бенд — декор, не тема; email-
  клиенты `prefers-color-scheme` не держат надёжно.
- Email-safe сохраняем: 600px, инлайн, bulletproof + solid-fallback под
  градиентом (Outlook), `safeHref` XSS-гард не трогаем.
- ВНЕ scope (follow-up из TASK-072 Details): user-facing «TrendPulse» в
  backend-subject'ах писем и NOWPayments order_description
  (`api/auth/users.py:48-49`, `billing/constants.py:19`,
  `billing/gateway/nowpayments.py:83`) — это backend, не templates.)
</content>
