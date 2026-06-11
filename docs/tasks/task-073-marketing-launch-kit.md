---
id: TASK-073
title: Маркетинговый launch-kit — X-аккаунт, SEO-статьи /blog/*, каталоги, closed-alpha
status: review              # planned → in-progress → review → done
owner: infra
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "c390c4c"
branch: "task/073-marketing-launch-kit"
tags: [launch, marketing, landing, content, runbook, growth]
---

# TASK-073 — Маркетинговый launch-kit (контент + owner-шаги)

> Продукт задеплоен, витрина (TASK-070) и лендинг живут — но о продукте никто не знает:
> ноль внешних точек входа кроме самого showcase-канала. Launch-kit = минимальный
> дистрибуционный набор: (a) X/Twitter-аккаунт с proof-of-speed закрепом, (b) 2–3
> SEO-статьи на лендинге, (c) сабмиты в каталоги, (d) closed-alpha на 10–20 человек
> из крипто-комьюнити с первой обратной связью. Runbook-стиль (как 059/060/070):
> код — ТОЛЬКО blog-страницы лендинга; остальное — owner-шаги с чёткими AC.

## Context

Лендинг config-driven: `landing/public/config.json` (цены 29/99 — источник производный
от `docs/product/overview.md` §6, урок task-017). Паттерн статических страниц:
`landing/src/pages/legal/*` — generic-рендерер `legal-page.tsx` + `legal-layout.tsx`;
роуты — `landing/src/app/router/router.ts` (legal-импорты стр. 12–18, path-блоки
50–94); список маршрутов для sitemap/SEO — `src/shared/site/routes.ts` (`SITE_ROUTES`),
head-теги per-route — `src/shared/seo/seo.ts::buildHeadTags`. Гейты контента уже в
репо: `npm run build` гоняет `sitemap:gen` + tsc (`landing/package.json:11`),
`npm run seo:validate` валидирует title/description/дубли по ВСЕМ SITE_ROUTES
(`landing/scripts/validate-seo.ts`). Footer: `root-layout.tsx:172-179` (колонка
Product). Proof-of-speed данные для закрепа: публичный `GET /api/v1/cases`
(TASK-045; operator-confirmed кейсы с lead-time). Обратная связь для alpha уже
инструментирована: 👍/👎 в алертах (TASK-042), активационная воронка (TASK-050),
money-dashboard (TASK-051). Урок task-018 (landing-base): НЕ публиковать
нереализованное — все тексты сверяются с overview §6 и фактическим кодом.

## Goal

После задачи: X-аккаунт компании живой (bio, закреп с proof-of-speed кейсом,
≥5 постов); 3 SEO-статьи на лендинге под /blog/* проходят `seo:validate` и попадают
в sitemap; PH-черновик готов (сабмит — после стабильной недели аптайма),
alternativeto + крипто-каталоги засабмичены; 10–20 alpha-приглашений отправлены,
первые 👍/👎 и кейсы собраны. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Формат SEO-статей? → A: статические страницы лендинга → Decision: **/blog/\* по
  паттерну legal-страниц** (тот же router.ts + SITE_ROUTES + buildHeadTags) — нулевая
  новая инфраструктура, статьи автоматически проходят sitemap:gen и seo:validate.
  CMS/markdown-pipeline не вводим (3 статьи, не блог-платформа). Кодовая часть
  ВКЛЮЧЕНА в эту задачу (а не вынесена): без неё AC по статьям непроверяем.
- Q: Темы статей? → A: три из ТЗ → Decision: (1) «How to detect viral Telegram
  content early» (how-to, органика по ключам); (2) «TrendPulse vs TGStat/Telemetr»
  (сравнение — ЧЕСТНОЕ: мы — alert-first детектор, они — каталоги/статистика;
  не принижать чужие факты, не приписывать себе нереализованное); (3) «Crypto
  payments guide» (как платить криптой за подписку — NOWPayments, снимает фрикцию
  E4-аудитории). Блог-индекс /blog (списком из 3 ссылок) — минимальный, по тому же
  паттерну.
- Q: X-аккаунт — handle? → A: бренд → Decision: @foresignal (дефолт; занят →
  @foresignal_biz / @trendpulse_fs — финал за owner'ом, фиксируется в Details).
  Bio: одна строка value-prop + ссылка foresignal.biz. Закреп — proof-of-speed кейс
  из `GET /api/v1/cases` (реальный lead-time, скрин поста showcase-канала со штампом
  «обнаружено в HH:MM»).
- Q: Каталоги — какие и когда? → A: поэтапно → Decision: **Product Hunt** — черновик
  сейчас, сабмит ТОЛЬКО после 7 подряд зелёных дней внешнего аптайм-монитора
  (TASK-060) — фейл на PH дороже отсрочки; **alternativeto.net** (категории
  TGStat/Telemetr alternatives) — сразу; крипто-каталоги — 2–3 из списка:
  CoinGecko ecosystem listings не про нас → реалистичный список: dappradar нет
  (не dapp) → берём каталоги инструментов: alternativeto, Product Hunt,
  crypto-twitter треды + telegram-каталоги (tgstat.com/telemetr сами индексируют
  публичный канал автоматически — проверить появление канала 070 в их индексе).
  Излишний спам по 20 каталогам не делаем (низкий ROI, риск бренду).
- Q: Closed-alpha — кого и как мерим? → A: крипто-комьюнити owner'а → Decision:
  10–20 личных приглашений (DM, не паблик-бласт); каждому — бесплатный Pro-период
  (механизм: owner вручную, без кода промокодов — его нет и не пишем);
  «первые 👍/👎» = существующие feedback-кнопки TASK-042; «кейсы» = скрины/цитаты
  с разрешения. Метрика успеха — в AC5 (активация по TASK-050-воронке).
- Q: Кто пишет тексты? → A: агент пишет черновики, owner утверждает → Decision:
  статьи и X-черновики готовятся в do-стадии, owner вычитывает ДО публикации
  (бренд-голос + юридическая честность — финальная ответственность owner'а).

## Scope
> **landing (blog-страницы) + контент-артефакты + owner-runbook.** Backend/SPA/цены
> НЕ трогаем. Owner-шаги помечены **[owner]**.

- **Touch ONLY:**
  - `landing/src/pages/blog/` — **новые**: `blog-index.tsx`, 3 статьи (`*.tsx` по
    паттерну `pages/legal/legal-page.tsx` — generic-рендерер или простые страницы,
    решает do-стадия по минимальному diff).
  - `landing/src/app/router/router.ts` — роуты `/blog`, `/blog/<slug>` ×3 (по образцу
    legal-блока, стр. 50–94).
  - `landing/src/shared/site/routes.ts` — `SITE_ROUTES` +4 (sitemap + seo:validate
    подхватят автоматически).
  - `landing/src/shared/seo/seo.ts` — head-записи (title/description) для 4 роутов.
  - `landing/src/pages/layouts/root-layout.tsx:172-179` — footer Product: ссылка Blog.
  - `landing/public/sitemap.xml` — регенерат (`npm run sitemap:gen`, артефакт сборки).
  - Контент-артефакты вне кода **[owner совместно]**: X-аккаунт, PH-черновик,
    каталоги, alpha-приглашения — процедуры и тексты фиксируются в
    `docs/full-system-test.md`-чеклисте ИЛИ разделе Details этого дока (решит
    do-стадия: один источник, без нового каталога docs/marketing).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `landing/public/config.json` (цены/контакты — источники 049/060),
  legal-страницы, `frontend/**`, `backend/**`, pricing-копию (источник overview §6),
  SPA, `docs/product/overview.md` (статьи ССЫЛАЮТСЯ на факты, не меняют их).
- **Blast radius:** лендинг (+4 статические страницы — аддитивно, существующие роуты
  не трогаются); sitemap (+4 url); внешние поверхности (X/PH/каталоги) — вне кода,
  обратимы (удалить пост/листинг).

## Acceptance Criteria

- [ ] **AC1 — X-аккаунт живой.** Given аккаунт создан When смотрим профиль Then
  bio с value-prop + ссылка foresignal.biz, закреп — proof-of-speed кейс (реальный
  lead-time из /api/v1/cases + скрин поста канала), опубликовано ≥5 постов
  (не за один день — растянуть на неделю).
- [ ] **AC2 — статьи проходят гейты.** Given 3 статьи + /blog-индекс When
  `npm run build` и `npm run seo:validate` Then зелёные: уникальные title/description
  на каждом роуте, sitemap содержит 4 новых url; lint/tsc чистые.
- [ ] **AC3 — честность контента.** Given любой опубликованный текст (статьи, X,
  PH-черновик) When сверяем с overview §6 и фактическим кодом Then ни одного
  обещания нереализованного (нет «приоритетного скоринга», «AI-предсказаний»,
  несуществующих интеграций); цены = 29/99 (как в config.json); сравнение с
  TGStat/Telemetr не содержит ложных утверждений о конкурентах.
- [ ] **AC4 — каталоги.** PH-черновик заполнен (tagline, галерея, first-comment)
  и ждёт триггера «7 зелёных дней аптайма» (TASK-060-монитор); alternativeto-листинг
  засабмичен; появление showcase-канала в индексе tgstat/telemetr проверено
  (или зафиксировано «ещё не индексирован»).
- [ ] **AC5 — alpha запущена.** Given 10–20 приглашений отправлены When проходит
  2 недели Then ≥5 человек дошли до активации (по воронке TASK-050: регистрация →
  подписка на пак → первый алерт), собраны первые 👍/👎 (TASK-042) и ≥2 цитаты/кейса
  с разрешением на публикацию.
- [ ] **AC6 — воспроизводимость.** Процедуры (X-постинг-ритм, PH-сабмит-триггер,
  alpha-онбординг) зафиксированы письменно — следующий итерация маркетинга не
  начинается с нуля.

## Plan

1. Blog-инфраструктура: 4 страницы + роуты + SITE_ROUTES + seo-записи + footer-ссылка
   (по паттерну legal); черновики 3 статей (контент сверен с overview §6) →
   `npm run build` + `seo:validate` → AC2.
2. **[owner]** Вычитка статей → merge → деплой лендинга → статьи живые.
3. **[owner]** X-аккаунт: handle из Discussion → bio → закреп (кейс из /api/v1/cases
   + скрин канала 070) → план 5 постов на неделю (черновики готовит do-стадия) → AC1.
4. PH-черновик (тексты/галерея) + **[owner]** alternativeto-сабмит; проверка индексации
   канала в tgstat/telemetr → AC4. PH-сабмит — отложенный триггер (7 зелёных дней).
5. **[owner]** Alpha: список 10–20 контактов → DM-шаблон (из do-стадии) → ручная
   выдача Pro → наблюдение воронки 050/051 две недели → AC5.
6. Процедуры в письменный вид (AC6) → ship кодовой части не ждёт AC5 (см. Details).

## Invariants

- **Не обещать нереализованное** (урок task-018) — каждый внешний текст проходит
  AC3-сверку ДО публикации; сомнение = вычеркнуть.
- Цены/факты в статьях — производные от overview §6 (урок task-017: расхождение
  чинится от overview, статьи не становятся вторым источником истины).
- Блог — статика по существующему паттерну: никакой новой инфраструктуры
  (CMS, markdown-pipeline, комментарии) в этой задаче.
- Личные данные alpha-участников не публикуются; цитаты — только с явного разрешения.
- PH-сабмит строго после стабильной недели (внешний монитор TASK-060) — нельзя
  звать толпу на продукт, который может лечь.

## Edge cases

- Handle @foresignal занят в X → варианты из Discussion; фиксируется в Details +
  единый handle во всех текстах (статьи на него не ссылаются — лендинг = хаб).
- /api/v1/cases пуст (ни одного operator-confirmed кейса) → закреп без конкретного
  lead-time невозможен → ИЛИ подтвердить кейс по процедуре 045 до шага 3, ИЛИ закреп
  = скрин поста канала со штампом (слабее, но честно); НЕ выдумывать цифры.
- Showcase-канал (070) ещё не активирован к моменту X-постов → посты без скринов
  канала, закреп переделывается после 070 (deps-порядок: 070 раньше).
- Alpha-активация <5 из 20 за 2 недели → это РЕЗУЛЬТАТ (сигнал об онбординге/ценности),
  не провал задачи: фиксируем причины из фидбека в learnings → вход следующей
  продуктовой итерации; AC5 закрывается отчётом, не дотягиванием цифры.
- Сравнительная статья вызывает реакцию TGStat/Telemetr → все утверждения о
  конкурентах — проверяемые факты с их публичных страниц (дата проверки в тексте).
- seo:validate падает на дублях title → у статей полностью уникальные title
  (не «Blog — TrendPulse» ×3) — проверяется AC2 локально до PR.

## Test plan

- Код (landing): `npm run build` (tsc + sitemap:gen), `npm run lint`,
  `npm run seo:validate` — AC2; визуальная проверка 4 страниц (десктоп/мобайл),
  футер-ссылка работает; существующие роуты не сломаны (smoke по главной/pricing).
- Контент: AC3-сверка построчно против overview §6 + grep по запрещённым обещаниям
  (паттерн review-стадии task-018/044: «приоритетный скоринг», несуществующие фичи).
- Runbook-воспроизводимость: процедуры AC6 проходимы «чистым исполнителем».
- security (5.5): skip-кандидат (статический контент, нет input/auth/secrets) —
  подтвердить на review: в статьях/скринах нет токенов, личных email, внутренних URL.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 7
baseline_commit: "c390c4c"
branch: "task/073-marketing-launch-kit"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (blog-страницы + черновики всех текстов + runbook-процедуры — Details)
- [x] 4 verify (G2 2026-06-11: unit 24/24, lint clean, build+sitemap 17 url,
  seo:validate 17 routes ok, e2e против прод-сборки 21 passed / 2 skipped;
  live AC1/AC4/AC5 — owner-таймлайн, blocked-список O1–O8 в Details)
- [x] 5 review (adversarial, фокус честность: 2 правки — history «paid plans only»,
  дедуп formatBlogDate; AC3-grep чист, инварианты закреплены юнит-тестами)
- [x] 5.5 security (skip подтверждён: статический контент, нет input/auth/secrets;
  diff просканирован — токенов/личных данных/внутренних URL нет)
- [x] 6 ship (кодовая часть + черновики; owner-шаги — blocked-список O1–O8 в Details)
- [ ] 7 learnings (в отчёте исполнителя; docs/learnings.md — вне scope этого запуска)
debug_runs: []

## Details

(planned 2026-06-11. Дистрибуционный хвост запуска: продукт без точек входа.
Deps: TASK-057 (живой прод — без него некуда звать), TASK-070 (showcase-канал —
источник скринов/закрепа и сам по себе канал дистрибуции), TASK-067 (landing-хвост —
блог встаёт на тот же лендинг; конфликтов по файлам нет, но порядок merge учесть).
Ship-модель как у 059/060: кодовая часть (blog) + все черновики мержатся сразу;
owner-шаги (X, PH-триггер, alpha, 2-недельное наблюдение AC5) — blocked-список,
закрывается по мере исполнения. AC5-таймлайн (2 недели) НЕ держит ship.)

(do 2026-06-11, executor. Решения do-стадии:
**Кодовая часть.** Блог = реестр статей `landing/src/shared/blog/articles.ts`
(slug/path/title/seoTitle/seoDescription/datePublished/readingTime/excerpt — единый
источник для индекса, seo.ts и тестов) + generic-рендерер
`pages/blog/blog-article-layout.tsx` (блог-близнец `legal-page.tsx`, проза вместо
аккордеона) + `blog-index.tsx` + 3 статьи. SEO: blog-ветка в `routeMeta` читает
реестр (switch не разрастается), статьи получают JSON-LD `BlogPosting`.
Slug'и зафиксированы: `/blog/detect-viral-telegram-content-early`,
`/blog/telegram-trend-alerts-vs-tgstat-telemetr` (бренд в slug НЕ зашит),
`/blog/crypto-payments-for-saas-guide`. Бренд везде через `SITE.brandName`;
цены в крипто-гайде интерполируются из `SITE.pricing.plans` (урок task-017) —
оба инварианта закреплены юнит-тестами `tests/unit/blog.test.ts` (скан исходников
на литерал бренда, на `$NN`-литералы, на запрещённые обещания из урока task-018,
на дату проверки фактов о конкурентах).
**Runbook/черновики.** Один источник = этот раздел (full-system-test.md не трогаем:
маркетинг — не системный тест). Все внешние тексты ниже прошли AC3-сверку
с overview §6 / config.json до записи.)

### Owner-runbook (blocked-список; зеркало для MANUAL-TODO §8)

Статусы проставляет owner по мере исполнения. Код/черновики уже в репо.

- [ ] **O1 — X-аккаунт (AC1).** Handle: `@foresignal`; занят → `@foresignal_biz`
  → `@trendpulse_fs` (финальный выбор вписать сюда). Website: `https://foresignal.biz`.
  Bio (EN, ≤160):
  > Detect viral Telegram content before it explodes. Real-time alerts from public
  > channels, measurable lead time. Free plan available.
- [ ] **O2 — закреп (AC1).** Взять operator-confirmed кейс из
  `GET https://foresignal.biz/api/v1/cases` (реальные `first_seen`/`lead_time`) +
  скрин поста showcase-канала (TASK-070) со штампом «detected HH:MM UTC». Шаблон:
  > "{title}" — detected {HH:MM} UTC, mainstream pickup {HH:MM} UTC.
  > {N} min ahead. Viral score {score}.
  > Spotted automatically in public Telegram channels. Live feed: {showcase_url}
  > Try it: https://foresignal.biz
  Кейсов нет → подтвердить кейс по процедуре TASK-045 ИЛИ закреп = скрин поста
  канала со штампом, без цифр. Цифры НЕ выдумывать.
- [ ] **O3 — 5 постов за неделю (AC1).** Ритм: 1 пост/будний день, далее 2–3/нед.
  Черновики (EN):
  1. **Intro.** «Most "breaking" Telegram news is hours old by the time you see it.
     Foresignal watches public channels and alerts you when a story *starts*
     spreading — with a first-seen timestamp, so the lead time is measurable, not
     marketing. https://foresignal.biz»
  2. **How it works.** «How we detect viral content early: 1) read public channels
     in your watchlist 2) cluster the same story across channels (rephrased,
     translated — still one story) 3) score the spread velocity 4) alert when it
     crosses your threshold. Public channels only, raw content discarded after 48h.»
  3. **Proof-of-speed кейс.** Шаблон O2 с другим кейсом из /api/v1/cases + скрин.
  4. **Blog: how-to.** «Manual playbook for spotting viral Telegram posts before
     mainstream: cross-channel repetition, first-hour velocity, upstream channels.
     And why it stops scaling past a few dozen channels →
     https://foresignal.biz/blog/detect-viral-telegram-content-early»
  5. **Blog: честное сравнение.** «TGStat and Telemetr are great channel catalogs.
     We are not one. Alert-first vs catalog-first — an honest comparison of which
     tool fits which job →
     https://foresignal.biz/blog/telegram-trend-alerts-vs-tgstat-telemetr»
  Правило: каждый пост с цифрами — только из /api/v1/cases; AC3-сверка перед
  публикацией (сомнение = вычеркнуть).
- [ ] **O4 — Product Hunt черновик (AC4).** Заполнить на producthunt.com/posts/new,
  НЕ сабмитить до триггера «7 подряд зелёных дней внешнего аптайм-монитора
  (TASK-060)»; дату старта зелёной серии вписать сюда: ____.
  - Name: Foresignal; Tagline (≤60): «Viral Telegram trends, detected before they
    explode»; Topics: Analytics, Social Media, Crypto.
  - Description: «Foresignal monitors public Telegram channels, clusters the same
    story across channels and alerts you the moment it starts spreading — with a
    first-seen timestamp and measurable lead time. Telegram bot + webhook delivery,
    API on the top plan. Crypto payments (NOWPayments), free plan available.
    Public channels only; raw content discarded after 48 hours.»
  - Gallery: скрин hero лендинга; скрин алерта в Telegram; секция proof-of-speed
    (/#proof-of-speed); скрин pricing; скрин showcase-канала.
  - First comment (maker): «Maker here. Foresignal started as a personal tool:
    I wanted to know about breaking crypto stories before the big aggregators
    posted them. It reads public Telegram channels, clusters the same story across
    channels and scores how fast it spreads. Every detection records its lead time
    vs mainstream pickup — that number is the product. Happy to answer anything,
    including why payments are crypto-only.»
- [ ] **O5 — alternativeto.net (AC4).** Засабмитить приложение
  (alternativeto.net/manage-item/) как alternative to TGStat и Telemetr.
  Описание — первый абзац PH-description (O4). Лицензия: Freemium.
- [ ] **O6 — индексация showcase-канала (AC4).** Проверить появление канала 070
  в tgstat.com и telemetr.io (поиск по @handle). Не индексирован → у tgstat есть
  форма «добавить канал» (tgstat.com/add) — добавить вручную; результат/дату
  вписать сюда: ____.
- [ ] **O7 — closed-alpha приглашения (AC5).** 10–20 личных DM из крипто-комьюнити
  owner'а (НЕ паблик-бласт). Шаблон DM (EN; допустим личный перевод, фактов не
  менять):
  > Hey {name} — I built a thing you might actually use. Foresignal watches public
  > Telegram channels and pings you when a story starts going viral (before the big
  > channels pick it up; lead time is measured per detection). I'm inviting 10–20
  > people I trust to a closed alpha — you get the Pro plan free for the test
  > period, set up in ~5 minutes. Interested? https://foresignal.biz
  Pro выдаётся вручную owner'ом (механизма промокодов нет и не пишем). Каждому
  приглашённому: попросить честный 👍/👎 на алертах (кнопки TASK-042) и разрешение
  цитировать фидбек.
- [ ] **O8 — наблюдение 2 недели (AC5).** Воронка TASK-050 (регистрация → пак →
  первый алерт) + money-dashboard TASK-051. Цель: ≥5 активаций, ≥2 цитаты/кейса
  с явным разрешением. <5 активаций — тоже результат: причины из фидбека →
  learnings → вход следующей итерации. Отчёт вписать сюда: ____.

### Процедуры (AC6 — воспроизводимость)

1. **X-постинг-ритм:** 2–3 поста/нед после стартовой недели; типы: кейс
   (шаблон O2, данные только из /api/v1/cases), how-it-works/компл-факт, ссылка на
   blog-статью. Перед каждым постом — AC3-чек: факт есть в overview §6/config.json?
   нет → не публикуем. Личные данные пользователей — никогда.
2. **PH-сабмит-триггер:** ежедневный аптайм-монитор TASK-060; 7 подряд зелёных
   дней → сабмит O4 во вторник–четверг; день сабмита — отвечать на каждый
   комментарий; фейл аптайма в серии → счётчик заново.
3. **Alpha-онбординг:** DM (O7) → регистрация → owner вручную включает Pro →
   через 3 дня спросить «получил первый полезный алерт?» → через 2 недели — итог
   по воронке 050 + сбор цитат (только с явного разрешения).
4. **Новая статья в блог:** добавить запись в `articles.ts` + страницу в
   `pages/blog/` + роут в `router.ts` + путь в `SITE_ROUTES`; meta подхватятся
   seo.ts/sitemap автоматически; гейты: `npm run test:unit && npm run build &&
   npm run seo:validate` (юнит-тесты сами проверят уникальность title, отсутствие
   литерала бренда и захардкоженных цен).
