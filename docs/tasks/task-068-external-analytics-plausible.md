---
id: TASK-068
title: Внешняя аналитика — Plausible Cloud на landing + SPA, согласование cookie-текстов
status: planned             # planned → in-progress → review → done
owner: frontend
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: ""
tags: [landing, frontend, analytics, privacy, legal-copy]
---

# TASK-068 — Внешняя аналитика: Plausible (privacy-first, cookieless)

> Сейчас у продукта НЕТ внешней web-аналитики вообще (grep gtag/plausible/posthog
> по landing и frontend = 0), при этом legal-копия уже «обещает» Google Analytics 4.
> Ставим Plausible Cloud на лендинг + SPA (custom events: `sign_up_click`,
> `pricing_view`), чиним cookie-policy/DPA/do-not-sell под фактический стек.

## Context

Аналитики нет: в `landing/index.html`, `frontend/index.html` и обоих `src/` нет ни
одного analytics-скрипта. Зато legal-страницы лендинга упоминают GA4, которого нет
и не будет: `landing/src/pages/legal/cookie-policy.tsx:108-112` (строка таблицы
`_ga, _ga_*` / Google Analytics 4), `:131` (Third-Party: Google Analytics 4),
`landing/src/pages/legal/do-not-sell-or-share.tsx:50` («e.g., Google Analytics 4»),
`landing/src/pages/legal/dpa.tsx:176-177` (субпроцессор «Google LLC (GA4)»).

Cookie-banner (`landing/src/shared/ui/cookie-banner.tsx`) хранит согласие в
localStorage (`cookie-consent`/`cookie-preferences`, `:9-10`) с toggle'ами
analytics/marketing (`:140-164`).

SSR-лендинг инжектит head-теги per-route через `buildHeadTags`
(`landing/src/shared/seo/seo.ts:116-148`, вызов из `landing/server/ssr/render.tsx:73`)
— естественная точка для скрипта на ВСЕХ страницах лендинга, config-driven через
`SITE` (= `landing/public/config.json`). SPA — обычный Vite `frontend/index.html`.

CSP проверен: ни в `development/provisioning/nginx/nginx.conf:84-88`, ни в релизном
шаблоне `release/provisioning/nginx/templates/nginx.conf.template:99-102,123-126`
заголовка `Content-Security-Policy` НЕТ (только HSTS/nosniff/X-Frame-Options/
Referrer-Policy) → правка nginx не требуется.

Воронка активации внутри продукта уже есть (TASK-050, `business_metrics_daily`) —
Plausible закрывает ВЕРХ воронки (visit → sign_up click), стыкуясь с
backend-метриками по событию регистрации.

## Goal

Plausible-скрипт грузится на всех страницах лендинга и в SPA (домен — из конфига,
пустое значение = аналитика выключена); события `sign_up_click` (landing CTA + SPA
sign-up) и `pricing_view` (landing /pricing) долетают в Plausible; legal-копия
упоминает Plausible вместо GA4; cookie-banner честен (cookieless-аналитика +
opt-out). Настройка goals в дашборде Plausible — owner-шаг. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Какой провайдер аналитики? → A: → Decision: **Plausible Cloud**. Rationale:
  privacy-first и **cookieless** — не ставит куки и не собирает personal data, т.е.
  consent-гейт для самой аналитики не нужен (критично: cookie-banner уже написан, но
  скрипт-гейтинга нет — с GA4 пришлось бы строить настоящий consent-флоу); скрипт
  <1KB (лендингу важен LCP); продукт для крипто-аудитории — Google-трекер подрывает
  «Privacy-история» (позиционирование security-privacy-секции). Альтернативы
  отклонены: **GA4** — требует consent-флоу (EEA), куки `_ga*`, противоречит
  крипто-аудитории; **PostHog** — session replay/feature flags сейчас не нужны,
  тяжелее скрипт и бесплатный тир шумный. Самохостинг Plausible CE отклонён: +1
  контейнер/домен на и без того тесном VPS (bridge-подсети исчерпаны) — Cloud $9/mo
  дешевле опс-времени.
- Q: Один сайт в Plausible или два (foresignal.biz + app.foresignal.biz)? → A: →
  Decision: **один сайт `foresignal.biz`**, на обоих приложениях
  `data-domain="foresignal.biz"` — Plausible агрегирует поддомены в один property;
  воронка visit→sign_up видна в одном дашборде. Значение домена — из конфига
  (`config.json`), не хардкод.
- Q: Как сделать config-driven на лендинге и в SPA? → A: лендинг весь читает
  `public/config.json`; SPA конфигурится build-time → Decision: лендинг — новое поле
  `config.json` `"plausibleDomain": "foresignal.biz"` (пустая строка → тег не
  рендерится), скрипт-тег добавляется в `buildHeadTags` (`seo.ts`) — попадает на все
  SSR-страницы; SPA — статический тег в `frontend/index.html` (если во frontend уже
  есть env-механизм `VITE_*` для подобного — do-стадия использует его, иначе
  статический тег с тем же доменом; минимальный diff решает do).
- Q: Какие custom events? → A: задача фиксирует два → Decision: `sign_up_click` —
  на CTA-кнопках лендинга (`hero.tsx:26-30`, `final-cta.tsx:20-24`,
  `root-layout.tsx:80-83` и mobile `:136-143`) и на submit формы
  `frontend/src/pages/auth/sign-up.tsx`; `pricing_view` — на маунте
  `landing/src/pages/pricing.tsx`. Хелпер `track(event)` — безопасный no-op, если
  `window.plausible` отсутствует (заблокирован/выключен) — клики НИКОГДА не ломаются.
  Имена событий — named constants. Больше событий не добавляем (G1: верх воронки,
  остальное уже меряет TASK-050 server-side).
- Q: Goals в Plausible? → A: настройка дашборда — вне репо → Decision: **owner-шаг**
  (создать сайт foresignal.biz, добавить goals `sign_up_click`/`pricing_view`);
  фиксируется в Details как послемёрджный хвост.
- Q: Нужен ли analytics-toggle в cookie-banner при cookieless Plausible? → A:
  юридически consent не требуется (нет куки, нет personal data), но toggle уже
  показан пользователям; молча выкинуть = жест недоверия, оставить мёртвым = обман →
  Decision: toggle ОСТАВИТЬ и сделать честным — маппить на стандартный opt-out
  Plausible (`localStorage["plausible_ignore"]="true"` при analytics=false и при
  «Reject All»); текст секции упростить: «cookieless, no cookies set, anonymous
  aggregate stats». Banner целиком остаётся — он гейтит будущий marketing-пиксель.
- Q: CSP? → A: проверено — CSP-заголовка нет ни в dev-, ни в release-nginx →
  Decision: nginx НЕ трогаем; в Details — заметка «при будущем введении CSP добавить
  `script-src plausible.io` + `connect-src plausible.io`».
- Q: Загрузку скрипта гейтить consent'ом? → A: cookieless → не требуется →
  Decision: скрипт грузится всегда (если домен в конфиге непуст); opt-out — через
  `plausible_ignore` (см. выше). Это документируется в cookie-policy.

## Scope
> **landing** (head-теги, события, cookie-тексты) + **frontend** (тег + событие).
> Backend, nginx, cookie-consent storage-ключи — не трогаем.

- **Touch ONLY:**
  - `landing/public/config.json` — поле `"plausibleDomain": "foresignal.biz"`.
  - `landing/src/shared/seo/seo.ts` — в `buildHeadTags` (`:129-145`) условный
    `<script defer data-domain="${SITE.plausibleDomain}" src="https://plausible.io/js/script.js">`
    (URL скрипта — named constant).
  - `landing/src/shared/analytics/track.ts` — **новый**: `track(event)` no-op-safe
    хелпер + константы `EVENT_SIGN_UP_CLICK` / `EVENT_PRICING_VIEW` + типизация
    `window.plausible`.
  - `landing/src/pages/sections/hero.tsx` (`:26-30`),
    `landing/src/pages/sections/final-cta.tsx` (`:20-24`),
    `landing/src/pages/layouts/root-layout.tsx` (`:80-83`, `:136-143`) — onClick →
    `track(EVENT_SIGN_UP_CLICK)`.
  - `landing/src/pages/pricing.tsx` — `pricing_view` на маунте.
  - `landing/src/shared/ui/cookie-banner.tsx` — `rejectAll`/`savePreferences`
    (`:61-71`): запись/снятие `plausible_ignore`; текст Analytics-секции (`:140-151`).
  - `landing/src/pages/legal/cookie-policy.tsx` — `:108-112` строка `_ga` →
    убрать/заменить (Plausible куки не ставит — отразить честно), `:131` GA4 →
    Plausible (cookieless).
  - `landing/src/pages/legal/do-not-sell-or-share.tsx` — `:50` GA4 → Plausible.
  - `landing/src/pages/legal/dpa.tsx` — `:176-177` «Google LLC (GA4)» →
    «Plausible Insights OÜ (EU) — privacy-first web analytics».
  - `frontend/index.html` — Plausible-тег в `<head>` (`:3-10`).
  - `frontend/src/pages/auth/sign-up.tsx` — `sign_up_click` на submit (+ мини-хелпер
    или дублирование 5-строчного track — по числу call-sites решит do; не тащим
    общий пакет ради одного события).
  - `landing/tests/e2e/` — новый/расширенный spec (см. Test plan).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** nginx-конфиги (`development/provisioning/**`,
  `release/provisioning/**` — CSP отсутствует), `backend/**` (server-side метрики =
  TASK-050), ключи localStorage `cookie-consent`/`cookie-preferences` (обратная
  совместимость сохранённых выборов), `landing/server/**`, прочие legal-страницы
  (privacy-policy.tsx упоминает «analytics» без бренда — корректно).
- **Blast radius:** head всех страниц лендинга (+1 defer-скрипт — LCP-нейтрально),
  CTA-клики (track обязан быть no-op-safe — иначе сломаем главную конверсию),
  cookie-banner-флоу (только тексты + side-effect `plausible_ignore`), SPA index.html.
  Юридическая копия: cookie-policy/DPA/do-not-sell начинают соответствовать
  реальности (сейчас — нет).

## Acceptance Criteria

- [ ] **AC1 — скрипт.** Given `plausibleDomain: "foresignal.biz"` When SSR любой
  страницы лендинга Then в `<head>` ровно один Plausible-тег с
  `data-domain="foresignal.biz"`; Given `plausibleDomain: ""` Then тега нет.
  В `frontend/index.html` тег присутствует.
- [ ] **AC2 — события.** Given `window.plausible` доступен When клик по CTA
  (hero/final-cta/nav) Then вызван `plausible('sign_up_click')` и переход по href
  состоялся; When открыт `/pricing` Then `plausible('pricing_view')` вызван один раз.
  Given `window.plausible` отсутствует (blocked) When клик по CTA Then переход
  работает, ошибок в консоли нет.
- [ ] **AC3 — opt-out.** Given пользователь выключил Analytics-toggle (или Reject
  All) Then `localStorage["plausible_ignore"]==="true"`; Given включил обратно Then
  ключ снят. Сохранённые ранее `cookie-consent`/`cookie-preferences` читаются как
  прежде.
- [ ] **AC4 — legal-копия.** `grep -rn "Google Analytics\|GA4\|_ga" landing/src` = 0
  совпадений; cookie-policy описывает Plausible как cookieless; DPA-таблица
  субпроцессоров содержит Plausible Insights OÜ.
- [ ] **AC5 — G2.** `npm run lint` + `tsc --noEmit` + landing e2e (включая
  `smoke.spec.ts`) зелёные; `npm run seo:validate` зелёный; ручная проверка в
  браузере: запрос к `plausible.io/api/event` уходит при клике на CTA.

## Plan

1. `landing/src/shared/analytics/track.ts` — хелпер + константы (RED: e2e-ассерты
   на отсутствие ошибок при blocked plausible; unit при наличии каркаса).
2. `seo.ts` + `config.json` — условный тег в `buildHeadTags`.
3. CTA-обвязка: `hero.tsx`, `final-cta.tsx`, `root-layout.tsx`, `pricing.tsx`.
4. `cookie-banner.tsx` — `plausible_ignore` + упрощённый текст Analytics-секции.
5. Legal-копия: `cookie-policy.tsx`, `do-not-sell-or-share.tsx`, `dpa.tsx`.
6. Frontend: `index.html` тег + `sign-up.tsx` событие.
7. e2e + lint/tsc + seo:validate; ручная проверка событий в Plausible-дашборде
   (или network-tab, если сайт в Plausible ещё не заведён owner'ом).

## Invariants

- Лендинг остаётся config-driven: домен аналитики — ТОЛЬКО из `config.json`
  (`plausibleDomain`); пустое значение полностью выключает фичу. URL скрипта —
  named constant, не размазан по файлам.
- CTA-переходы (sign-up) работают при любом состоянии аналитики: blocked, выключена,
  упала — `track` никогда не бросает и не препятствует навигации.
- Legal-страницы описывают только фактический стек (урок task-018: не публиковать
  ложные раскрытия) — после задачи в них нет GA4, есть Plausible.
- Cookie-consent-ключи и их формат не меняются (сохранённые выборы пользователей
  валидны).
- `npm run seo:validate` зелёный (head-теги страниц не потеряли title/description).

## Edge cases

- Adblock режет `plausible.io` → скрипт не грузится, `window.plausible` undefined →
  `track` = no-op, UX не страдает (AC2).
- `plausible_ignore` выставлен, но скрипт загружен → Plausible сам уважает этот ключ
  (штатный механизм) — событий нет.
- Пользователь с ранее сохранённым `cookie-consent="essential"` (до этой задачи) →
  `plausible_ignore` у него не выставлен; do-стадия решает: выставлять ретроактивно
  при чтении старого consent'а (1 строка в эффекте баннера) — зафиксировать выбор
  в Details.
- SSR-страница 404 (`not-found.tsx`) → тег тоже присутствует (buildHeadTags общий) —
  ок, Plausible сам считает 404-страницы.
- `pricing_view` в StrictMode/повторный маунт → событие должно слаться один раз на
  визит страницы (guard в эффекте).

## Test plan

- e2e (playwright, `landing/tests/e2e/`): (1) head содержит plausible-тег с верным
  data-domain; (2) клик по hero-CTA при заблокированном `plausible.io`
  (`page.route` → abort) — переход на signupUrl без console errors; (3) перехват
  `plausible.io/api/event` через `page.route` — клик CTA даёт событие
  `sign_up_click`, визит /pricing — `pricing_view`; (4) cookie-banner: Reject All →
  `plausible_ignore === "true"` в localStorage; (5) /cookie-policy и /dpa не
  содержат «Google Analytics».
- e2e existing: `smoke.spec.ts` без регрессий.
- static: AC4-grep как шаг verify; `npm run lint`, `tsc --noEmit`,
  `npm run seo:validate`.
- security: отдельная стадия не требуется (третьесторонний скрипт — фиксированный
  first-party-вендор; секретов/инпута нет). Review проверит, что скрипт подключён
  только с `plausible.io` и без проксирования.

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

(planned 2026-06-11. Зависимости: TASK-018 (landing base, done), TASK-050
(server-side воронка, done — Plausible закрывает верх воронки). Owner-хвосты после
merge: завести сайт `foresignal.biz` в Plausible Cloud (тариф Growth $9/mo),
добавить goals `sign_up_click` и `pricing_view`. Заметка на будущее: при введении
CSP в nginx добавить `script-src https://plausible.io` и
`connect-src https://plausible.io`.)
