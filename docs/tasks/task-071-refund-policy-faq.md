---
id: TASK-071
title: Refund policy (7-day money-back, USDT вручную) + расширение FAQ под крипто-онбординг
status: planned             # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [landing, legal, refund, faq, seo, conversion]
---

# TASK-071 — Refund policy + FAQ: снять страх «крипта без chargeback»

> Оплата криптой = нет chargeback'а — для покупателя это страх. Снимаем его явной
> страницей `/refund-policy` (7-day money-back на первый платёж, возврат вручную в
> USDT через support@) + расширяем FAQ ответами на реальные предпродажные вопросы
> (как платить криптой без опыта, задержка Free, паки, API-ключ, отмена).

## Context

Текущая копия противоречит будущей политике: ToS-секция Billing
(`landing/src/pages/legal/terms-of-service.tsx:138` id `billing`) прямо говорит
«fees are non-refundable» (`:153-154`), а FAQ-ответ про refund отсылает в ToS
(`landing/src/pages/sections/faq.tsx:47-50`). Оплата — только крипта через
NOWPayments (`terms-of-service.tsx:161-163`, ADR-004), боевой платёжный путь
проверяется в TASK-058.

Legal-страницы строятся по единому паттерну: компонент `LegalPage`
(`landing/src/pages/legal/legal-page.tsx:11` — title/lastUpdated/intro/items-аккордеон),
данные из `SITE` (= `landing/public/config.json`: `legal.effectiveDate`,
`contactEmail`); образец — `cookie-policy.tsx`. Роут добавляется в трёх местах:
`landing/src/app/router/router.ts` (createRoute + routeTree `:98-111`),
`landing/src/shared/site/routes.ts:1-14` (`SITE_ROUTES` — отсюда автоматически
строятся sitemap `scripts/generate-sitemap.ts:18` и SEO-валидация
`scripts/validate-seo.ts:19`), `landing/src/shared/seo/seo.ts:21-69` (`routeMeta`
— title/description, иначе validate-seo упадёт... точнее отдаст default «Not Found»
title — дубликат → warning; кейс для нового роута обязателен).

FAQ — секция на home (`faq.tsx`, 10 вопросов), отдельной страницы НЕТ; nav и footer
ведут на `/#faq` (`root-layout.tsx:67-69`, `:176`). В FAQ замечен дрейф от TASK-049:
`faq.tsx:24` «(Free: none; Pro: 30 days; Team: 90 days)» и `:54` «Pro and Team
customers» — верхний тариф давно «Trader» на всех остальных витринах.

Footer Legal-список — `root-layout.tsx:191-200`; pricing-страница —
`landing/src/pages/pricing.tsx` (paymentNote `:24-25` — рядом логично жить
refund-ссылке).

## Goal

Страница `/refund-policy` живёт по паттерну legal-страниц, залинкована из footer и
pricing; ToS Billing-секция согласована с ней (7-day money-back на первый платёж);
FAQ на home отвечает на 5 предпродажных вопросов крипто-новичка и больше не
противоречит refund-политике; `/refund-policy` в sitemap, `npm run seo:validate`
зелёный. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Какая refund-политика? → A: крипта необратима (нет chargeback), автоматических
  возвратов NOWPayments не даёт → Decision: **7-day money-back guarantee на ПЕРВЫЙ
  платёж** (любой план), возврат **вручную в USDT** по письму на
  `support@foresignal.biz` (адрес — из `SITE.contactEmail`, не хардкод), срок
  обработки — до 10 рабочих дней; **продления — case-by-case** (без гарантии,
  рассматриваем индивидуально). Rationale: явная и честная ручная процедура снимает
  главный страх крипто-оплаты и дёшево исполняется при текущих объёмах (первые
  платящие); ограничение «первый платёж» защищает от abuse «оплатил → выкачал
  историю → вернул».
- Q: В какой валюте/курсе возврат? → A: курс плавает между оплатой и возвратом →
  Decision: возвращаем **эквивалент уплаченной USD-цены инвойса в USDT** на момент
  возврата (сумма инвойса — источник истины, как в биллинге TASK-049/AC4). EU-право
  отзыва (14 дней) НЕ отменяется этой политикой — упоминание в ToS остаётся.
- Q: Отдельная FAQ-страница или расширить секцию home? → A: секция уже есть, nav
  ведёт на `/#faq`, отдельная страница = дубль контента и каннибализация SEO →
  Decision: **расширяем `faq.tsx`** (+5 вопросов: оплата криптой без опыта — шаги
  NOWPayments-чекаута; что значит задержка Free 30 мин; что такое паки (curated
  packs); как получить API-ключ (Trader); как отменить подписку — крипта = предоплата,
  не продлеваешь и всё). Существующий refund-ответ (`faq.tsx:47-50`) переписываем
  ссылкой на `/refund-policy`.
- Q: Чинить ли «Team» → «Trader» в faq.tsx? → A: дрейф от TASK-049 в файле, который
  и так в diff'е → Decision: чиним обе строки (`:24`, `:54`) здесь — отдельная
  задача дороже однострочного фикса; фиксируем в Details для AC3-grep'а 049.
- Q: ToS «fees are non-refundable» — переписать или дополнить? → A: противоречие
  убивает доверие к обеим страницам → Decision: bullet Refunds (`:153-154`)
  переписать: 7-day money-back на первый платёж по Refund Policy (ссылка), далее —
  non-refundable кроме требований закона (EU withdrawal остаётся). ToS — краткая
  норма, детали процедуры — только на `/refund-policy` (один источник истины).
- Q: Числа политики (7 дней, 10 раб. дней) — в config.json? → A: legal-копия
  лендинга хардкодит тексты в tsx (паттерн всех существующих legal-страниц,
  переменные — только entity/email/dates из `SITE.legal`) → Decision: числа в копии
  страницы, БЕЗ нового config-поля (не плодим конфиг ради одного потребителя);
  `lastUpdated` — из `SITE.legal.effectiveDate`, как у соседей.

## Scope
> Только **landing** (новая страница + роутинг + копия + тесты). Backend/биллинг не
> трогаем — политика исполняется вручную через support.

- **Touch ONLY:**
  - `landing/src/pages/legal/refund-policy.tsx` — **новый**: `LegalPage` с items:
    guarantee (7-day, первый платёж), how-to-request (письмо на support@ с email
    аккаунта + tx-данными), refund-method (USDT, эквивалент USD-цены инвойса, до 10
    раб. дней), renewals (case-by-case), eu-rights (14-day withdrawal), contact.
  - `landing/src/app/router/router.ts` — `refundPolicyRoute` + в `routeTree`
    (`:98-111`).
  - `landing/src/shared/site/routes.ts` — `'/refund-policy'` в `SITE_ROUTES`
    (sitemap + validate-seo подхватят автоматически).
  - `landing/src/shared/seo/seo.ts` — case `'/refund-policy'` в `routeMeta`
    (`:21-69`): title/description.
  - `landing/src/pages/layouts/root-layout.tsx` — пункт «Refund Policy» в
    footer-список Legal (`:191-200`).
  - `landing/src/pages/pricing.tsx` — ссылка на `/refund-policy` рядом с paymentNote
    («7-day money-back on your first payment»).
  - `landing/src/pages/legal/terms-of-service.tsx` — bullet Refunds (`:153-154`) →
    новая формулировка + `<Link to="/refund-policy">`.
  - `landing/src/pages/sections/faq.tsx` — +5 вопросов, переписать refund-ответ
    (`:47-50`), попутный фикс Team→Trader (`:24`, `:54`).
  - `landing/public/sitemap.xml` — регенерация (`npm run sitemap:gen`, входит в
    `npm run build`) — руками не правится.
  - `landing/tests/e2e/refund-faq.spec.ts` — **новый** (см. Test plan).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `backend/**` (никакой автоматизации возвратов — ручная
  процедура), `landing/public/config.json` (новых полей не требуется),
  остальные legal-страницы (privacy/cookie/aup/dpa — refund их не касается),
  `landing/server/**`, `frontend/**`, nginx/provisioning, `_bmad/**`, `.claude/**`.
- **Blast radius:** роутинг лендинга (новый лист в `routeTree` — изолированно);
  `SITE_ROUTES`-производные: sitemap.xml (+1 url), validate-seo (+1 route — упадёт,
  если забыть case в `routeMeta`, что и нужно); юридическая связка ToS ↔ Refund
  Policy (правим обе стороны в одном diff'е); FAQ-копия (предпродажная конверсия).

## Acceptance Criteria

- [ ] **AC1 — страница.** Given лендинг запущен When открывается `/refund-policy`
  Then 200, заголовок «Refund Policy», аккордеон-секции: 7-day money-back на первый
  платёж, процедура через `support@foresignal.biz` (значение из `SITE.contactEmail`),
  возврат в USDT, renewals case-by-case, EU 14-day withdrawal; lastUpdated из
  `SITE.legal.effectiveDate`.
- [ ] **AC2 — ссылки.** Given любая страница When смотрим footer Then в Legal-списке
  есть ссылка Refund Policy; Given `/pricing` Then возле paymentNote есть ссылка на
  `/refund-policy`; Given `/terms-of-service` секция Billing Then refund-bullet
  ссылается на `/refund-policy` и НЕ содержит безусловного «non-refundable».
- [ ] **AC3 — FAQ.** Given `/` секция FAQ Then присутствуют вопросы: оплата криптой
  для новичка, задержка Free-алертов, что такое packs, как получить API-ключ, как
  отменить подписку; refund-вопрос ссылается на `/refund-policy`; в тексте FAQ нет
  «Team» как имени тарифа (только «Trader»).
- [ ] **AC4 — SEO.** `/refund-policy` есть в `SITE_ROUTES`, в регенерированном
  `sitemap.xml` и имеет уникальные title/description; `npm run seo:validate`
  зелёный (0 missing, 0 duplicate warnings по новому роуту).
- [ ] **AC5 — G2.** `npm run lint` + `tsc --noEmit` + `npm run build` + landing e2e
  (новый spec + `smoke.spec.ts`) зелёные.

## Plan

1. e2e RED: `refund-faq.spec.ts` — `/refund-policy` 200 + ключевые формулировки,
   footer/pricing/ToS-ссылки, новые FAQ-вопросы (падает на baseline).
2. `refund-policy.tsx` — страница по образцу `cookie-policy.tsx` (LegalPage).
3. Роутинг: `router.ts` → `routes.ts` → `seo.ts` (порядок: компонент → роут →
   SITE_ROUTES → routeMeta; validate-seo ловит пропуски).
4. Ссылки: `root-layout.tsx` (footer) + `pricing.tsx`.
5. Копия: `terms-of-service.tsx` (Refunds bullet) + `faq.tsx` (+5 вопросов,
   refund-ответ, Team→Trader).
6. `npm run sitemap:gen` (через build) — регенерация sitemap.xml.
7. GREEN: e2e + lint + tsc + seo:validate.

## Invariants

- Лендинг остаётся config-driven: email/entity/даты — только из `SITE`
  (`config.json`), в копии нет захардкоженных адресов/доменов.
- Один источник истины по refund-процедуре — `/refund-policy`; ToS и FAQ только
  ссылаются, не дублируют детали (расхождение копий невозможно по построению).
- `sitemap.xml` генерируется, не редактируется руками; `npm run seo:validate`
  зелёный; каждый новый роут одновременно в `routeTree`, `SITE_ROUTES`, `routeMeta`.
- Витрины не обещают нереализованное (урок task-018): автоматического refund-флоу
  в продукте нет — страница описывает ручную процедуру через support, без
  кнопок/форм «request refund» в SPA.
- EU statutory withdrawal right упоминается и не сужается (юридический минимум).

## Edge cases

- Пользователь требует возврат на 8-й день → политика явно «within 7 days of your
  first payment» (дата платежа = дата инвойса); case-by-case оговорка покрывает
  пограничные случаи доброй волей, не обязательством.
- Возврат за продление (второй+ платёж) → страница прямо говорит case-by-case —
  ожидание не создаётся.
- Курс USDT изменился → возвращается USD-эквивалент суммы инвойса (фиксируем в
  копии), не «те же монеты».
- Прямой заход на `/refund-policy` (без клиента-роутера) → SSR отдаёт 200 с полным
  HTML — покрыто самим паттерном (все legal-страницы так работают), e2e проверяет.
- `routeMeta` забыт → title = «Not Found»-default → validate-seo предупредит о
  дубликате; шаг 3 плана упорядочен, AC4 закрывает.

## Test plan

- e2e (`landing/tests/e2e/refund-faq.spec.ts`, playwright по образцу
  `smoke.spec.ts`): (1) `/refund-policy` — 200, money-back/USDT/first payment в
  тексте, email из config; (2) footer-ссылка с home ведёт на страницу; (3) `/pricing`
  содержит refund-ссылку; (4) `/terms-of-service` — refund-bullet ссылается на
  `/refund-policy`; (5) home FAQ — 5 новых вопросов раскрываются, текст «Trader»
  присутствует, «Team» как тариф — нет.
- e2e existing: `smoke.spec.ts` без регрессий (FAQ-секция и pricing меняются).
- static: `npm run lint`, `tsc --noEmit`, `npm run seo:validate`,
  `npm run build` (включает sitemap:gen).
- security: не требуется (статическая копия, нет input/auth/secrets).

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "c390c4c"
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11. Зависимости: TASK-018 (landing base, done), TASK-058 (боевой
платёжный путь, in-progress — refund-страница описывает процедуру поверх него;
кодовой связи нет, публиковать страницу можно до полного закрытия 058). Попутный
фикс дрейфа Team→Trader в `faq.tsx:24,54` — хвост AC3 задачи 049. Owner-хвост:
support@ должен реально отвечать (uptime/support — TASK-060).)
