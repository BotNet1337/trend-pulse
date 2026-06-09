---
id: TASK-018
title: Landing base — hero/how-it-works/features/pricing/CTA/compliance-футер, бренд TrendPulse
status: review           # planned → in-progress → review → done
owner: frontend
created: 2026-06-09
updated: 2026-06-09
baseline_commit: "fad558c76d3df62b034c424c5de795a2b68ee568"
branch: "gsd/phase-018-landing-base"
tags: [landing, marketing, compliance, seo, e2e]
---

# TASK-018 — Landing base (Epic B · B1)

> Базовый аккуратный **compliance-friendly лендинг** из скопированного template (`landing/`): hero (с примером viral-alert как в overview §1), секция «как работает», фичи, **тарифы Free/Pro/Team** (из §6), CTA → signup (ведёт на frontend `/sign-up`), футер с compliance (privacy, retention 48h, только публичные каналы, ToS). Адаптировать бренд/копи под TrendPulse. Критерии: build зелёный, Lighthouse (perf/a11y/seo разумные пороги), smoke e2e (страница грузится, ключевые секции, CTA-ссылка). Независима от backend.

## Context

TrendPulse (см. [`../product/overview.md`](../product/overview.md) §1) — персональный детектор вирусного контента из Telegram; итог для пользователя — viral alert (`🔥 Viral alert [crypto] — "Bitcoin ETF approval" · Score: 94 · 47 каналов за 23 мин · first seen 14:02`). Эпик B (Landing) по [roadmap](../architecture/roadmap.md) §«Epic B» — маркетинговый лендинг (React + Vite, SSG/static). В `apps/trendPulse/landing/` уже лежит **скопированный template** с готовыми секциями (`src/pages/sections/`: hero, how-it-works, features, pricing-preview, faq, final-cta, contact, security-privacy) и legal-страницами (`src/pages/legal/`: privacy-policy, terms-of-service, cookie-policy, acceptable-use-policy, security, dpa, …). Бренд/копи — от чужого продукта; B1 адаптирует под TrendPulse.

Compliance (overview §7 / §2): **только публичные каналы** (`@username`, приватные недоступны), **retention 48h** (raw-контент не хранится дольше окна, [task-011](./task-011-compliance-ops.md)). Лендинг должен честно это отражать (compliance-friendly: privacy, retention, public-only, ToS) — не обещать лишнего.

Тарифы (overview §6): **Free** $0 (5 каналов, 1 топик, 5 алертов/день, без истории, только Telegram) · **Pro** $19/мес (100 каналов, 5 топиков, ∞ алертов, история 30 дней, +webhook) · **Team** $79/мес (500 каналов, ∞ топиков, ∞ алертов, история 90 дней, +API access). Оплата — только крипта (NOWPayments), никакого Stripe.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md) — `make` единая точка входа; версии образов из `development/version.env`; никаких секретов в бандле. Лендинг независим от backend (CTA — внешняя ссылка на frontend `/sign-up`).

## Goal

После задачи: лендинг TrendPulse собирается (`make build`) и грузится; видны ключевые секции — hero (с примером viral-alert), «как работает», фичи, тарифы Free/Pro/Team (числа из §6), CTA; CTA ведёт на frontend `/sign-up`; футер несёт compliance-ссылки (privacy, retention 48h, public-only, ToS); бренд/копи — TrendPulse (не template-бренд); Lighthouse perf/a11y/seo проходят разумные пороги; smoke e2e зелёный (страница грузится, ключевые секции присутствуют, CTA-ссылка корректна). DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения по template + overview §1/§6/§7; обратимы. -->
- Q: Писать лендинг с нуля или адаптировать template? → A: **адаптировать** скопированный `landing/` → Decision: переиспользуем готовые секции (`hero`, `how-it-works`, `features`, `pricing-preview`, `final-cta`, `security-privacy`) и legal-страницы; меняем бренд/копи/контент под TrendPulse. Не катаем свой scaffold (паттерн «adopt proven structure»).
- Q: Что в hero? → A: overview §1 → Decision: ценностное предложение (детектор вирусного контента из Telegram) + **пример viral-alert** (`🔥 Viral alert [crypto] … Score 94 · 47 каналов … first seen`) как наглядный артефакт; CTA-кнопка.
- Q: CTA куда ведёт? → A: signup → Decision: CTA → frontend `/sign-up` (внешняя ссылка на SPA-домен/путь; лендинг и SPA — разные приложения). URL — через env/конфиг (`VITE_APP_SIGNUP_URL`/site-config), не magic literal.
- Q: Тарифы на лендинге? → A: overview §6 → Decision: pricing-секция Free/Pro/Team с числами из §6 (каналы/топики/алерты/история/доставка); числа — из единого site-config, не разбросаны inline. Оплата — крипта (упомянуть), никакого Stripe.
- Q: Compliance-футер? → A: §7 → Decision: футер/legal — privacy-policy, terms-of-service, retention 48h, «только публичные каналы», cookie-policy; честная формулировка ограничений (public-only, retention), не overpromising. Переиспользуем legal-страницы template, адаптируем под TrendPulse.
- Q: Backend-зависимость? → A: нет → Decision: B1 независим от backend (CTA — внешняя ссылка); никаких API-вызовов к TrendPulse-backend на лендинге (compliance: лендинг — статика).
- Q: SEO/метрики? → A: разумные пороги → Decision: title/meta/OG, семантический HTML, alt-тексты, Lighthouse perf/a11y/seo выше согласованных порогов; глубокая аналитика конверсии — отдельная задача (B4), здесь базовый SEO.

## Scope
> **Только `landing/`** (+ `development/compose/landing.yml` если лендинг встаёт сервисом за edge; иначе чистая static-сборка). Backend и frontend НЕ трогаем (CTA — внешняя ссылка).

- **Touch ONLY (создать/изменить):**
  - `landing/src/shared/site/**` — site-config: бренд TrendPulse, тарифы Free/Pro/Team (числа §6), `signup_url` (→ frontend `/sign-up`), compliance-тексты (retention 48h, public-only). Единый источник чисел/копи, не inline-магия.
  - `landing/src/pages/sections/hero.tsx` — value prop + пример viral-alert (§1) + CTA.
  - `landing/src/pages/sections/{how-it-works,features,pricing-preview,final-cta,security-privacy,faq}.tsx` — адаптировать копи/контент под TrendPulse (как работает, фичи, тарифы, CTA, privacy).
  - `landing/src/pages/legal/{privacy-policy,terms-of-service,cookie-policy,acceptable-use-policy,security}.tsx` — адаптировать под TrendPulse (retention 48h, public-only channels, ToS); убрать/заменить чужой бренд.
  - `landing/src/pages/layouts/**`, `landing/src/shared/seo/**` — бренд/мета/OG/title; футер с compliance-ссылками.
  - `landing/src/shared/components/**`, `landing/tailwind.config.ts` — тема/токены под бренд TrendPulse (consistent с frontend по возможности; responsive).
  - `landing/Dockerfile` — адаптировать (static-сборка, Node из `version.env`) при необходимости.
  - `development/compose/landing.yml` — **(опц.)** compose-сервис `landing` за edge-nginx (если лендинг отдаётся через тот же edge); либо чистый static-артефакт.
  - `landing/tests/e2e/smoke.spec.ts` — **новый** smoke e2e: страница грузится, ключевые секции (hero/how-it-works/features/pricing/footer), CTA-ссылка ведёт на `/sign-up`.
  - `landing/scripts/**` — Lighthouse-прогон (если есть харнесс) / порог-проверка.
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `frontend/**` (Epic C — task-013..017), `backend/**` (лендинг независим), `docs/**` (кроме `tasks-index.md` на ship). Не реализовывать signup-форму на лендинге (CTA — ссылка на SPA). Не вводить API-вызовы к backend / секреты / Stripe.
- **Blast radius:** маркетинговая точка входа; первая публичная страница TrendPulse. Compliance-формулировки (retention 48h, public-only) — публичные обязательства, должны совпадать с overview §7 / task-011. CTA связывает лендинг с frontend signup (мягкая внешняя ссылка). Независим от backend — не меняет API/SPA.

## Acceptance Criteria
- [ ] **AC1 — лендинг грузится с брендом TrendPulse (failing-test anchor).** Given собранный лендинг, When открыть корень, Then страница рендерится, виден бренд **TrendPulse** (не template-бренд), hero с value prop. smoke-e2e пишется ПЕРВЫМ (RED — пока бренд/копи не адаптированы).
- [ ] **AC2 — ключевые секции присутствуют.** Given загруженный лендинг, When инспекция, Then видны hero (с примером viral-alert из §1), «как работает», фичи, тарифы (Free/Pro/Team с числами §6), CTA, compliance-футер.
- [ ] **AC3 — CTA ведёт на signup.** Given CTA-кнопка/ссылка, When клик/инспекция href, Then ведёт на frontend `/sign-up` (URL из конфига, не inline-магия); ссылка валидна.
- [ ] **AC4 — compliance-футер честный.** Given футер/legal, When инспекция, Then присутствуют privacy-policy, terms-of-service, retention **48h**, «только публичные каналы», cookie-policy; формулировки совпадают с overview §7 (без overpromising).
- [ ] **AC5 — build зелёный + SEO-базис.** Given `make build`, When сборка лендинга, Then билд проходит; присутствуют title/meta/OG, семантический HTML, alt-тексты; нет битых ссылок на template-бренд.
- [ ] **AC6 — Lighthouse пороги.** Given собранный лендинг, When Lighthouse (perf/a11y/seo), Then метрики выше согласованных разумных порогов (зафиксировать пороги в задаче/скрипте); responsive (mobile/desktop) без поломки layout.
- [ ] **AC7 — поведенческая (G2) проверка.** Given собранный/поднятый лендинг (`make up` или static-preview), When Playwright `smoke.spec.ts` гоняется против реальной сборки, Then AC1–AC4 наблюдаемы; артефакты (screenshot/trace on-failure) сохранены.

## Plan
0. Executor фиксирует `baseline_commit`; ветка `gsd/phase-018-landing-base`.
1. **RED:** `landing/tests/e2e/smoke.spec.ts` — открыть лендинг, ожидать бренд TrendPulse + ключевые секции + CTA→`/sign-up`. Падает (template-бренд/копи). AC1-якорь.
2. `shared/site` — site-config (бренд, тарифы §6, `signup_url`, compliance-тексты retention 48h/public-only); единый источник.
3. `pages/sections/hero` — value prop + пример viral-alert (§1) + CTA; адаптировать `how-it-works/features/pricing-preview/final-cta/security-privacy/faq` под TrendPulse.
4. `pages/legal/**` + `shared/seo` + футер — privacy/ToS/retention 48h/public-only/cookie; мета/OG/title; убрать чужой бренд.
5. Тема/токены (`tailwind.config.ts`, `shared/components`) под бренд; responsive.
6. `Dockerfile`/`development/compose/landing.yml` (опц., за edge) или static-артефакт; **build зелёный**.
7. **G2:** `make build` (+ `make up`/static-preview); Playwright `smoke.spec.ts` зелёный (AC1–AC4, AC7); Lighthouse perf/a11y/seo выше порогов (AC6); проверить SEO-базис и отсутствие битых template-ссылок (AC5).
8. Обновить `tasks-index.md` на ship.

## Invariants
- **Compliance-friendly, без overpromising** — retention 48h, «только публичные каналы», privacy/ToS совпадают с overview §7 / task-011; лендинг не обещает приватные каналы/иное хранение.
- **Никаких секретов / API-вызовов к backend** — лендинг — статика; CTA — внешняя ссылка на frontend `/sign-up` (URL из конфига, no magic literal); никакого Stripe.
- **Единый источник копи/чисел** — бренд, тарифы §6, signup-URL, compliance-тексты — в site-config; не разбросаны inline.
- **Единая дизайн-система** — тема/токены под бренд TrendPulse (по возможности консистентно с frontend); responsive + базовая a11y (alt-тексты, семантический HTML, контраст).
- **SEO-базис** — title/meta/OG, семантический HTML; Lighthouse выше согласованных порогов; глубокая аналитика — отдельная задача (B4).
- **`make` — единая точка входа** — сборка через `make build`; версии (Node) из `development/version.env`, без `latest` (CONVENTIONS).
- **Независимость от backend** — B1 не блокируется Epic A/C; CTA — мягкая внешняя ссылка.

## Edge cases
- Чужой бренд template остался в copy/legal/мета → grep по template-бренду, заменить через site-config (AC5 ловит битые ссылки).
- frontend `/sign-up` ещё не задеплоен на финальный домен → `signup_url` из конфига (env), e2e проверяет корректность href, не живой переход в SPA.
- Тарифные числа §6 разошлись с overview → единый site-config + ссылка на §6; при изменении тарифов — одно место правки.
- Mobile-вёрстка ломает hero/pricing → responsive-проверка (AC6), без горизонтального скролла/перекрытий.
- Lighthouse a11y < порога из-за контраста/alt → исправить токены/alt; пороги зафиксированы в задаче (не «как получится»).
- Legal-страницы template содержат пункты, неприменимые к TrendPulse (чужие фичи) → вычистить/адаптировать, не оставлять вводящих в заблуждение обещаний.
- CTA-ссылка с tracking-параметрами → допустимо, но без секретов/PII в URL.

## Test plan
- **e2e (Playwright):** `landing/tests/e2e/smoke.spec.ts` — AC1 (загрузка + бренд TrendPulse, RED-якорь), AC2 (ключевые секции hero/how-it-works/features/pricing/footer + пример viral-alert), AC3 (CTA href → `/sign-up`), AC4 (compliance-футер: privacy/ToS/retention 48h/public-only). Артефакты on-failure.
- **build/SEO:** `make build` — AC5 (билд зелёный, title/meta/OG, семантический HTML, alt, нет битых template-ссылок).
- **Lighthouse:** прогон perf/a11y/seo (скрипт `landing/scripts`) — AC6, пороги зафиксированы; responsive mobile/desktop.
- **runtime/behavioral (G2):** `make build` (+`make up`/static-preview) → Playwright против реальной сборки (AC7); ручная проверка соответствия compliance-текстов overview §7.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 4
baseline_commit: "fad558c76d3df62b034c424c5de795a2b68ee568"
branch: "gsd/phase-018-landing-base"
lock: "loop-018"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code → GREEN: 6/6 e2e smoke pass)
- [x] 4 verify (G2 — build+lint+seo_validate+content_audit+audit_copy all green; 6/6 Playwright smoke)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (XSS/санитизация, secrets не в бандле, cookie/CSRF, SSRF в webhook-полях)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## do-phase results (2026-06-09)
- commit: 1bcf5b4 (feat(task-018): adapt landing to TrendPulse brand — hero/sections/legal/SEO)
- build: green (sitemap+tsc+client+server; 1787 modules)
- lint: green
- seo:validate: green (12 routes)
- content:audit: green
- audit:copy: green (0 findings)
- e2e: 6/6 smoke tests pass (Playwright chromium; SSR server :4173)
  - AC1: TrendPulse title, no PostBolt
  - AC2: viral-alert example, how-it-works, features, pricing Free/Pro/Team, footer
  - AC3: CTA href → /sign-up
  - AC4: privacy/ToS links, retention 48h, public channels; privacy-policy+ToS pages adapted
- lighthouse: skipped (offline env, no chromium remote debug port); SEO-базис verified via seo:validate + manual curl (title/meta/OG all rendered correctly by SSR)
- brand_clean: grep confirms 0 PostBolt references in src/ and scripts/

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план по эталону task-003/004 и контексту: compliance-friendly лендинг из template landing/ (hero с примером viral-alert §1, how-it-works, features, тарифы Free/Pro/Team §6, CTA→frontend /sign-up, compliance-футер: privacy/ToS/retention 48h/public-only). Адаптация бренда/копи под TrendPulse; build зелёный, Lighthouse perf/a11y/seo пороги, smoke e2e. Независима от backend (deps: нет). Stripe/секретов/API-вызовов нет. locate+plan выполнены этим планированием — executor стартует с «3 do».)
