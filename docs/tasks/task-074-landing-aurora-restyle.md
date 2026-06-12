---
id: TASK-074
title: Landing Aurora restyle — привести реальный React-лендинг к дизайн-мокам landing-asis 1:1 (токены + полировка секций), канонизировать дизайн-токены
status: planned          # planned → in-progress → review → done
owner: frontend
created: 2026-06-12
updated: 2026-06-12
baseline_commit: "af5885a"
branch: ""
tags: [frontend, design-system, landing, restyle, tokens, polish]
---

# TASK-074 — Landing Aurora restyle (визуальное соответствие landing-asis)

> Реальный React-лендинг приводится к утверждённым дизайн-мокам
> `designs/trendPulse/landing-asis/` (визуальная цель). Это **только
> презентация**: токены дизайн-системы в `landing/src/app/app.css @theme`
> канонизируются как единый источник, секции/спейсинг/компоненты
> выравниваются под моки. Контент (тексты, цены, legal, blog) — verbatim,
> не переписывается. Бренд — «Foresignal» через `SITE.brandName`.
>
> Этот таск — фундамент для TASK-075 (email-шаблоны): он фиксирует
> канонические ЗНАЧЕНИЯ токенов, которые TASK-075 переиспользует инлайн.

## Context

Лендинг — React 19 + `@tanstack/react-router` + Tailwind v4 (`@tailwindcss/vite`),
SSR (fastify), EN-only. Структура: `landing/src/pages/{home,pricing,about,
contact,not-found}.tsx`, секции `landing/src/pages/sections/*` (hero,
social-proof, proof-of-speed, features, how-it-works, security-privacy,
pricing-preview, faq, final-cta, contact-section), legal `landing/src/pages/
legal/*` (8 страниц через `legal-layout.tsx`), блог `landing/src/pages/blog/*`,
UI-кит `landing/src/shared/components/*` (button, badge, card, input, accordion,
switch, theme-toggle, …), SEO `landing/src/shared/seo/seo.ts`, site-config
`landing/src/shared/site/{constants,routes,theme}.ts`, конфиг бренда —
`landing/public/config.json` (уже `brandName: "Foresignal"`, домен
foresignal.biz, цены Pro 29/78/278, Trader 99/267/950 — verbatim из TASK-049).

**Дельта токенов (снято на baseline `af5885a`):**
- Текущий `landing/src/app/app.css` — это shadcn/Vite **дефолтная**
  нейтральная палитра (НЕ кастомная «Aurora»): `:root` светлая
  (`--background:#ffffff`, `--primary:#2563eb`, `--card:#ffffff`,
  `--muted:#ececf0`, `--border:rgba(0,0,0,0.1)`), `.dark`
  (`--background:oklch(0.145 0 0)`, `--primary:#3b82f6`,
  `--foreground:oklch(0.985 0 0)`, `--border:oklch(0.269 0 0)`). Есть
  `@theme inline` (мост `--color-* → var(--*)`), `@custom-variant dark`,
  base-слой (типографика h1–h4), `html.home-scroll-snap` сниппет.
- Дизайн-мок `landing-asis/assets/landing.css` — **компилированный** Tailwind
  v4 (39 КБ). В нём те же семантические токены с фактически **теми же
  значениями**, что в реальном `app.css` (light `--primary:#2563eb`,
  `--card:#fff`, `--muted:#ececf0`, `--border:#0000001a`; dark
  `--background:#0a0a0a`, `--primary:#3b82f6`, `--foreground:#fafafa`,
  `--muted:#262626`, `--border:#262626`). Мок-разметка использует **только
  семантические утилиты** (`bg-card`, `text-muted-foreground`, `text-primary`,
  `bg-primary/10`, `border-border`) — ни одного arbitrary-hex. То есть
  «Aurora» в названии — это нейминг дизайнера; фактическая палитра мока — это
  blue-primary нейтральная тема с поддержкой light/dark.

**Дельта разметки:** реальные секции уже близки к мокам структурно (hero —
тот же класс-набор `pt-32 pb-16 px-6 lg:px-20 snap-start scroll-mt-16`, та же
example-alert карточка `bg-card border border-border rounded-xl p-5 shadow-sm
font-mono`, тот же `bg-muted/20` social-proof, та же proof-of-speed сетка
`grid …lg:grid-cols-3 gap-6`). Расхождение — **мелкое-среднее**: спейсинг,
hover-состояния (`hover:border-primary/50`, `group-hover:bg-primary/20`),
радиусы/тени карточек, точные размеры заголовков (`text-3xl md:text-4xl`),
наличие/отсутствие декоративных элементов и единообразие токенов между
страницами. Глобального редизайна лейаута НЕТ.

**Тема:** мок поддерживает light/dark (есть theme-toggle, скрипт читает
`localStorage.theme`, по умолчанию light + опциональный `.dark`); реальный
`theme.ts` поддерживает `system|light|dark`. То есть **не dark-only** —
сохраняем обе темы.

## Goal

Реальный лендинг визуально соответствует мокам `landing-asis` (страницы home,
pricing, about, contact, blog, blog-article, legal) в обеих темах; токены
дизайн-системы канонизированы в `app.css @theme` как единый источник (TASK-075
переиспользует те же значения инлайн). Контент, маршруты, SEO, аналитика,
compliance — без изменений. Ноль user-facing «TrendPulse». `build` + `lint` +
unit + e2e зелёные. DoD = AC.

## Discussion

- Q: dark-only или обе темы? → A: **обе** → Decision: мок имеет theme-toggle
  и `.dark`-ветку, реальный `theme.ts` — `system|light|dark`; убирать тему =
  регресс функциональности и UX. Сохраняем `system|light|dark`, выравниваем
  ОБЕ палитры под мок. (Аудит D6 «dark-only» относится к *app*-шеллу, не к
  лендингу; здесь решение durable — кандидат в reference-комментарий в
  `app.css`.)
- Q: насколько 1:1 с моками? → A: **визуальный паритет, не побайтовый** →
  Decision: цель — пиксельно-близкое соответствие секций/спейсинга/состояний
  на десктоп+mobile в обеих темах; допустимы расхождения, обусловленные React-
  компонентной природой (CVA-варианты кнопок, Radix-примитивы) при условии
  совпадения визуального результата. Критерий приёмки — поэкранное сравнение,
  а не diff HTML.
- Q: где единый источник токенов и как его переиспользует email? → A:
  `app.css @theme` — канон; email переиспользует ЗНАЧЕНИЯ → Decision:
  канонические значения токенов фиксируются в `landing/src/app/app.css`
  (`:root` light + `.dark` + `@theme inline`-мост) с коротким reference-блоком-
  комментарием (перечень значений brand/bg/card/muted/border/foreground для
  обеих тем). TASK-075 (email) **не импортирует** CSS (письма не умеют внешний
  CSS) — он берёт ТЕ ЖЕ значения и хардкодит инлайн. Контракт: при изменении
  токена тут — синхронно правится TASK-075. Зафиксировано в Invariants обоих
  тасков.
- Q: токены уже почти совпадают — что вообще менять? → A: канонизация +
  полировка → Decision: значения мока ≈ текущим, поэтому основная работа — НЕ
  переписать палитру, а (1) причесать `@theme`/reference как единый источник,
  (2) выровнять секции/состояния/спейсинг под моки там, где есть визуальные
  расхождения (hover, тени, радиусы, размеры заголовков, отступы), (3) убрать
  любые остаточные несоответствия токенам (hardcoded цвета в компонентах, если
  найдутся на do-стадии). Объём расхождения — **мелкий-средний**.
- Q: трогаем ли контент/цены/legal/blog? → A: нет → Decision: только
  презентация. Любая правка строки-текста, цены, legal-формулировки, blog-
  статьи — вне scope (verbatim). Если мок и реальный текст расходятся —
  **реальный текст приоритетен** (он уже прошёл TASK-049/072 копи-ревью);
  выравниваем под мок только визуал.
- Q: theme-toggle мока vs реальный? → A: оставляем реальный → Decision:
  `shared/components/theme-toggle.tsx` + `shared/site/theme.ts` —
  функциональны; визуально привести кнопку-тоггл к мок-стилю, логику не менять.
- Q: deps? → A: нет блокеров → Decision: config.json уже Foresignal (TASK-072),
  токены уже близки; задача автономна. TASK-075 зависит ОТ неё (нужны
  канонизированные значения), но не наоборот.

## Scope

> Только презентация: токены, классы, спейсинг, состояния. Ни контента, ни
> маршрутов, ни SEO-полей, ни аналитики, ни SSR-логики, ни backend.

- **Touch ONLY:**
  - `landing/src/app/app.css` — канонизация токенов: выверить `:root`(light)
    и `.dark` под значения мока (где расходятся), `@theme inline`-мост,
    добавить reference-комментарий с перечнем канонических значений (контракт
    для TASK-075). НЕ менять `html.home-scroll-snap`-секцию (поведение скролла).
  - `landing/src/pages/sections/*` — выравнивание секций под моки (спейсинг,
    hover-состояния, радиусы/тени карточек, размеры заголовков): hero,
    social-proof, proof-of-speed, features, how-it-works, security-privacy,
    pricing-preview, faq, final-cta, contact-section. **Только className/
    разметка-обёртки**, не тексты.
  - `landing/src/pages/{home,pricing,about,contact,not-found}.tsx` — обёрточные
    лейаут-классы под моки (если расходятся).
  - `landing/src/pages/blog/{blog-index,blog-article-layout}.tsx` — визуал под
    `blog.html`/`blog-article.html` (типографика статьи, карточки списка).
  - `landing/src/pages/legal/legal-layout.tsx` — единый restyle legal-обёртки
    под Aurora (аудит D5); сами legal-страницы-контент НЕ трогаем.
  - `landing/src/pages/layouts/root-layout.tsx` — хедер/футер/навигация под мок
    (спейсинг, цвета токенами).
  - `landing/src/shared/components/*` — UI-кит под мок-стиль (button CVA-
    варианты, badge, card, accordion, input, switch, theme-toggle): только
    стили/варианты, API компонентов сохранить.
  - `landing/src/shared/ui/cookie-banner.tsx` — визуал баннера под мок; текст и
    compliance-логику НЕ трогать.
  - Тесты, ассертящие классы/визуал, если падают (найти прогоном на do-стадии).
- **Do NOT touch:**
  - Любой user-facing **текст/копия** (hero-копия, фичи, FAQ, pricing-фичи,
    refund/EU-withdrawal, legal-тексты 8 страниц, blog-статьи) — verbatim.
  - Цены (Pro 29/78/278, Trader 99/267/950) и `public/config.json`.
  - Маршруты и `landing/src/shared/site/routes.ts` (`SITE_ROUTES`).
  - SEO: `landing/src/shared/seo/seo.ts` (canonical/OG/Twitter/JSON-LD),
    `landing/public/sitemap.xml` (17 url) — генерится `sitemap:gen`, в diff
    попасть не должен (откатить таймстемп-шум, урок TASK-060/072).
  - Аналитика: `shared/analytics/track.ts` и события `sign_up_click` (hero/CTA),
    `pricing_view` (pricing) — вызовы и имена событий не трогать.
  - proof-of-speed data-flow: `shared/cases/*` + `GET /cases`
    (`CASES_API_URL`) — только визуал карточек, не fetch-логику.
  - `showcaseTelegramUrl`-условный рендер в hero/footer — оставить как есть.
  - SSR/сервер (`landing/server/*`), роутер (`app/router/*`),
    `theme.ts`-логика (только визуал тоггла), `vite-env.d.ts`.
  - `gen.types.ts` (если есть в landing — не трогать; это контракт SPA).
  - `_bmad/**`, `.claude/**`, `tasks-index.md`.
- **Blast radius:** чисто презентационный — className-и, CVA-варианты,
  значения CSS-токенов. Логика рендера, данные, маршруты, SEO неизменны.
  Риск: (1) тесты/e2e, завязанные на классы/визуал — чинятся в том же diff;
  (2) регресс контраста/доступности в одной из тем — ловится поэкранным
  проходом обеих тем; (3) сдвиг токена ломает контракт с TASK-075 — TASK-075
  ещё planned, синхронизируется при его do-стадии.

## Acceptance Criteria

- [ ] **AC1 — визуальное соответствие landing-asis.** Given собранный лендинг
  (light и dark) When пройти home / pricing / about / contact / blog /
  blog-article / legal Then каждая страница визуально соответствует
  одноимённому моку `designs/trendPulse/landing-asis/*.html` (лейаут,
  спейсинг, карточки, состояния hover, типографика) в ОБЕИХ темах; расхождения
  — только обусловленные React-компонентами, визуальный результат совпадает.
- [ ] **AC2 — токены канонизированы.** Given `landing/src/app/app.css` Then
  `:root`(light) и `.dark` содержат канонические значения (совпадают с мок-
  палитрой), `@theme inline`-мост на месте, добавлен reference-комментарий с
  перечнем значений brand/bg/card/muted/border/foreground обеих тем (контракт
  для TASK-075); компоненты используют семантические токены (`bg-card`,
  `text-primary`, …), а не hardcoded-цвета.
- [ ] **AC3 — обе темы работают.** Given theme-toggle When переключение
  system→light→dark Then обе темы рендерятся без артефактов контраста; `.dark`
  применяется к `<html>`/`<body>`; SSR-первый кадр без FOUC-регресса.
- [ ] **AC4 — контент verbatim.** Given diff таска When grep по изменённым
  файлам Then ни одна user-facing строка (тексты, цены, legal, blog) не
  изменена — только className/стили/токены; `public/config.json` не в diff.
- [ ] **AC5 — нет user-facing TrendPulse.** Given собранный лендинг When
  `grep -rni 'trendpulse' landing/src landing/index.html` Then ноль
  user-facing совпадений (бренд из `SITE.brandName`; внутренние идентификаторы
  допустимы).
- [ ] **AC6 — маршруты + SEO сохранены.** Given лендинг When проверка Then все
  маршруты + `SITE_ROUTES` рендерятся; canonical/OG/Twitter/JSON-LD на месте;
  `sitemap.xml` = 17 url (не в diff); `seo:validate`/`content:audit` зелёные.
- [ ] **AC7 — аналитика/compliance сохранены.** Given hero/CTA и pricing Then
  `sign_up_click` и `pricing_view` шлются как прежде; cookie-баннер +
  compliance-футер на месте; `showcaseTelegramUrl`-ссылки в hero/footer
  рендерятся при заполненном конфиге.
- [ ] **AC8 — build/lint/e2e зелёные.** `npm run build` (tsc+client+server),
  `lint`, unit (`test:unit`), Playwright e2e — зелёные.

## Plan

1. RED: снять baseline-скриншоты реального лендинга (light+dark) для дельты;
   при наличии визуальных/класс-ассертов в `tests/` — добавить/обновить
   ассерт на канонические токены в `app.css` (например, что `--primary`
   light=`#2563eb` / dark=`#3b82f6`) → падает, если значение разъедется.
2. Токены: выверить `app.css` `:root`/`.dark`/`@theme` под мок-палитру,
   добавить reference-комментарий (контракт TASK-075) → GREEN токен-ассерт.
3. UI-кит: привести `shared/components/*` (button CVA, badge, card, accordion,
   input, switch, theme-toggle) к мок-стилю; убрать hardcoded-цвета на токены.
4. Секции: выровнять `pages/sections/*` под моки (спейсинг, hover, тени,
   радиусы, размеры заголовков) — посекционно, сверяясь с `index.html`.
5. Страницы: pricing/about/contact/not-found + blog (`blog-index`,
   `blog-article-layout`) + legal (`legal-layout`) + `root-layout` (хедер/
   футер) + cookie-banner — под одноимённые моки.
6. Прогнать `npm run build` + `lint` + `test:unit`; добить падающие класс-/
   визуал-ассерты; откатить sitemap-таймстемп-шум.
7. Verify: поэкранный проход обеих тем vs моки (AC1/AC3), grep AC4/AC5,
   `seo:validate`+`content:audit` (AC6), e2e (AC8).

## Invariants

- Только презентация: ни одного нового условия рендера, хука, fetch, маршрута,
  SEO-поля, события аналитики — лишь className/CVA-варианты/значения токенов.
- Контент verbatim: тексты, цены (Pro 29/78/278, Trader 99/267/950),
  refund/EU-withdrawal, legal, blog-статьи — байт-в-байт; при конфликте мок↔
  реальный текст приоритетен реальный.
- Бренд только через `SITE.brandName` — ноль хардкода «TrendPulse» в
  user-facing.
- Сохранены: маршруты + `SITE_ROUTES`; SEO (canonical/OG/Twitter/JSON-LD,
  sitemap 17 url); Plausible `sign_up_click`/`pricing_view`; proof-of-speed из
  `GET /cases` (`CASES_API_URL`); `showcaseTelegramUrl` в hero/footer;
  cookie-баннер + compliance-футер; `/blog`; `/refund-policy`.
- Темы: `system|light|dark` сохранены; НЕ dark-only.
- **Контракт токенов (для TASK-075):** канонические значения brand/bg/card/
  muted/border/foreground живут в `app.css @theme` + reference-комментарий;
  email переиспользует ТЕ ЖЕ значения инлайн. Изменение токена тут → синхронная
  правка TASK-075.
- `sitemap.xml` (генерат) в diff не попадает.

## Edge cases

- Контраст в light-теме: мок-карточки `bg-card`(белый) на `bg-muted/20` — на
  do-стадии проверить читабельность `text-muted-foreground` на обоих фонах
  (AA-контраст), особенно proof-of-speed `font-mono`.
- SSR + theme: первый кадр рендерится сервером без `localStorage` — проверить,
  что нет FOUC/мигания при гидрации в обеих темах (паттерн уже в `root.tsx`).
- `bg-primary/10` / `color-mix(in oklab, …)` — Tailwind v4 alpha-утилиты:
  убедиться, что компилируются одинаково в обеих темах (light `#2563eb`/10 vs
  dark `#3b82f6`/10).
- Hover-состояния (`hover:border-primary/50`, `group-hover:bg-primary/20`) — на
  тач-устройствах не должны «залипать»; проверить mobile.
- Legal-layout: 8 страниц делят один layout — restyle обёртки не должен сломать
  длинный контент (списки, таблицы, anchor-ссылки внутри privacy/terms).
- Blog-article типографика: длинная статья (`prose`-подобный блок) — выровнять
  spacing заголовков/списков/кода без потери verbatim-текста.
- `sitemap:gen` в `build` трогает `lastmod` — откатить как шум (урок TASK-060).

## Test plan

- unit (`test:unit`, tsx --test): токен-ассерт на канонические значения
  `app.css` (если вводится); существующие — зелёные.
- e2e (Playwright): существующие landing-спеки (smoke/навигация/SEO-мета) —
  зелёные; при наличии селекторов по классам — обновить под новые.
- Визуальная регрессия (ручная, verify-стадия): поэкранный проход home/
  pricing/about/contact/blog/blog-article/legal в light и dark vs моки
  `landing-asis/*.html` — это AC1, ядро приёмки.
- SEO: `npm run seo:validate` + `content:audit` — зелёные (canonical/OG/JSON-LD/
  sitemap не тронуты).
- security: не требуется (только презентация; подтвердить skip на review).

## Checkpoints

current_step: 3
baseline_commit: "af5885a"
branch: ""
lock: ""
- [x] 1 locate (scope + дельта токенов/разметки + blast radius)
- [x] 2 plan (G1 — минимальный, презентация-only)
- [ ] 3 do (TDD: токен-ассерт RED → канонизация app.css → UI-кит → секции →
      страницы/legal/blog; откат sitemap-шума)
- [ ] 4 verify (G2 — build+lint+test:unit+e2e; поэкранный проход обеих тем vs
      моки; grep AC4/AC5; seo:validate+content:audit)
- [ ] 5 review (adversarial: контраст обеих тем, отсутствие hardcoded-цветов,
      контракт токенов для TASK-075, verbatim-контент)
- [ ] 5.5 security (ожидаемо skip — только презентация)
- [ ] 6 ship (PR из ветки — оркестратор)
- [ ] 7 learnings (docs/learnings.md: дельта «Aurora»=нейминг, мок-палитра ≈
      shadcn-дефолт; контракт токенов app.css↔email)
debug_runs: []

## Details

(planned 2026-06-12, baseline `af5885a`. Locate-факты:
- «Aurora» в брифе — нейминг дизайнера; фактическая мок-палитра
  (`landing-asis/assets/landing.css`, компилированный Tailwind v4 39 КБ) ≈
  shadcn-дефолт, который УЖЕ в `app.css`: light `--primary:#2563eb`/`--card:#fff`/
  `--muted:#ececf0`/`--border:#0000001a`, dark `--background:#0a0a0a`/
  `--primary:#3b82f6`/`--foreground:#fafafa`/`--border:#262626`. Значения почти
  совпадают → основная работа не «перекрасить», а канонизировать токены +
  выровнять секции/состояния.
- Мок-разметка использует ТОЛЬКО семантические утилиты (`bg-card`,
  `text-muted-foreground`, `bg-primary/10`, `border-border`) — нет arbitrary-hex;
  реальный hero уже совпадает по класс-набору (`pt-32 pb-16 px-6 lg:px-20
  snap-start scroll-mt-16`, та же example-alert карточка). Объём расхождения —
  МЕЛКИЙ-СРЕДНИЙ (спейсинг/hover/тени/радиусы/размеры заголовков, единообразие
  токенов между страницами), глобального редизайна нет.
- Мок поддерживает light/dark (theme-toggle + `.dark` + localStorage-скрипт);
  реальный `theme.ts` — `system|light|dark`. Решение: НЕ dark-only, выравниваем
  обе палитры.
- config.json уже `brandName:"Foresignal"` (TASK-072) — ребренд лендинга не
  требуется, только grep-страховка AC5.
- Контракт с TASK-075: канонические значения токенов фиксируются в `app.css`
  (`@theme` + reference-комментарий); email переиспользует ЗНАЧЕНИЯ инлайн, CSS
  не импортирует.)
</content>
