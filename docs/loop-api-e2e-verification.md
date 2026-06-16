# Runbook — полная проверка API через фронт (`/loop` + `/trendpulse-executor`)

Автономная кампания: доказать, что **API полностью работает end-to-end через реальный фронт**
(nginx → SPA → FastAPI → Postgres/Redis → Mailpit/templates), домен за доменом, **браузерными
Playwright-e2e** (а не внутренними pytest-юнитами) + точечными ручными HTTP-пробами через nginx.

**В скоупе:** auth (register/login/logout/guard), email-флоу (verify + reset через Mailpit),
watchlists CRUD + лимиты плана + cross-tenant, alerts (список + cursor-пагинация + feedback),
api-keys (create/list/revoke + auth по ключу), billing/account (invoice-контракт без live-IPN,
GDPR `DELETE /account`), delivery-config (webhook), referral, packs/trending, cases, feedback,
email-unsubscribe, ssr, admin/ops-metrics, `/api/health` + `/api/ready`.

**Вне скоупа (НЕ проверяем):** скоринг/scorer, pipeline/кластеризация/эмбеддинги (ML), live
Telegram-сбор, live NOWPayments IPN settlement, live Google OAuth-редирект, showcase-автопостинг.
Для этих эндпоинтов проверяем **только контракт** (auth/валидация/HTTP-shape), не асинхронную
обработку. Реальный email-routing (Cloudflare) — прод/owner, вне локального скоупа; локально email =
Mailpit.

## Как запускать

1. Claude Code запускать **из** `apps/trendPulse` (там активны trendpulse-скиллы и хуки).
2. Стек уже задеплоен, но кампания гоняется **локально**: нужны Docker + `uv` + Node 22.
   Для merge-PR — git remote + `gh auth login` заранее (как в основном лупе).
3. Введи `/loop` **без интервала** (self-paced) и вставь промпт ниже. Луп останавливается на
   подтверждение merge каждого PR; ответь «подтверждаю» — продолжит со следующего домена.
   Когда все домены `verified` — завершится сам.

```
/loop
```

## Промпт (вставить после /loop)

> Ты — оркестратор автономной кампании **полной проверки API TrendPulse через реальный фронт**.
> Рабочая директория: `/Users/macbookpro16/work/botnet/apps/trendPulse`. Общайся по-русски.
> Соблюдай `docs/CONVENTIONS.md` и архитектуру в `docs/architecture/`. Источник истины по
> прогрессу — трекинг-док `docs/api-e2e-status.md` (создай его в BOOTSTRAP, если нет).
>
> **ЦЕЛЬ:** доказать, что **каждый домен API реально работает end-to-end через фронт** —
> браузерными Playwright-e2e против поднятого `make up` стека (nginx :80), плюс точечными
> ручными HTTP-пробами через nginx. НЕ внутренними pytest-юнитами. Луп идемпотентен: каждую
> итерацию заново читай статусы доменов с диска и продолжай. Обрабатывай **ровно один домен за
> итерацию**.
>
> **В СКОУПЕ (домены, в порядке):**
> 1. `health` — `/api/health`==200, `/api/ready`==200 (db+redis ok), фронт грузится (smoke.spec.ts).
> 2. `auth` — register→login(cookie)→`/users/me`→logout→401→guard-redirect→неверный пароль (friendly,
>    без enumeration)→дубль email (без enumeration)→кнопка Google ведёт на `/api/auth/google/authorize`
>    (auth.spec.ts).
> 3. `email` — verify-флоу (register→письмо в Mailpit→переход по ссылке→`is_verified=true`) и
>    reset-password (forgot→письмо→reset→логин новым паролем). Через Mailpit :8025 + сервис templates
>    :3100 (auth-verify-reset.spec.ts). **Mailpit обязан быть доступен** — иначе спеки скипаются;
>    если скип — это провал готовности, чини стек, а не маркируй verified.
> 4. `watchlists` — CRUD + лимит плана + чужой id→404 (watchlists.spec.ts).
> 5. `alerts` — список + cursor-пагинация + alert feedback (alerts.spec.ts).
> 6. `api-keys` — create/list/revoke + аутентификация запроса по ключу (api-keys.spec.ts).
> 7. `billing-account` — контракт `POST /billing/invoice` (live-IPN НЕ требуется; при пустом
>    NOWPAYMENTS_API_KEY ассертить корректный контракт/ошибку, не падать), отображение плана,
>    GDPR `DELETE /account` каскад (billing-account.spec.ts).
> 8. `delivery-config` — webhook config (валидация URL) через фронт/nginx.
> 9. `referral` — реферальный код/применение (через nginx-пробу, если нет фронт-спеки).
> 10. `packs-trending` — curated packs + trending bootstrap (через nginx-пробу/имеющийся UI).
> 11. `cases-feedback` — cases + feedback эндпоинты (контракт через nginx).
> 12. `email-unsubscribe` — `email_unsubscribe` роут (ссылка из письма → отписка).
> 13. `ssr` — SSR-страницы рендерятся (ssr.spec.ts).
> 14. `admin-metrics` — ops/admin-метрики (admin-metrics.spec.ts).
>
> **ВНЕ СКОУПА — НЕ проверять обработку, только контракт эндпоинта (auth/валидация/HTTP-shape):**
> scorer/скоринг, pipeline/кластеризация/эмбеддинги (ML), live Telegram-сбор, live NOWPayments IPN
> settlement, live Google OAuth-редирект, showcase. Никогда не поднимай ML-образ воркера ради этой
> кампании.
>
> **BOOTSTRAP (один раз за кампанию):**
> - Если `docs/api-e2e-status.md` нет → создай: таблица `| domain | status | evidence | pr |` со всеми
>   доменами выше в статусе `pending`.
> - Подними и прогрей стек **через `make` (не raw docker compose)**:
>   `make build` → `make up`. Если env-файлов нет (`development/env/{deploy.env,sensitive.env}`) →
>   `make ansible-unpack` (нужен `ops/ansible/.vault-pass`); если vault-пароля нет — **СПРОСИ**
>   пользователя один раз (или предложи CI-style dummy-env как в `.github/workflows/main-integration.yml`).
> - Гейт здоровья: цикл `curl -s -o /dev/null -w '%{http_code}' http://localhost/api/health` до `200`
>   (≤60 попыток × 3с); затем `curl -s http://localhost/api/ready` == 200. Mailpit: `curl -s
>   http://localhost:8025/api/v1/messages` отвечает. Не дошло до 200 → `make logs-once`, диагностируй,
>   при нерешаемом — HALT и вопрос.
> - Подготовь фронт-тулинг один раз: `cd frontend && npm ci && npx playwright install --with-deps chromium`.
>
> **ИТЕРАЦИЯ (один домен):**
> 1. **Выбор.** Прочитай `docs/api-e2e-status.md`. Возьми первый домен со `status != verified` в
>    порядке выше. Если все `verified` → ЗАВЕРШЕНИЕ.
> 2. **Прогон-как-есть (verify-first).** Запусти существующую e2e-спеку домена через фронт:
>    `cd frontend && npx playwright test tests/e2e/<spec>.spec.ts` (против nginx :80). Для доменов
>    без фронт-спеки — ручные HTTP-пробы через nginx (`curl` к `/api/v1/...` с cookie-сессией:
>    register→login→cookie-jar, как в `docs/full-system-test.md` §A3). Зафиксируй фактический
>    результат (pass/fail + артефакты Playwright: trace/screenshot/video на провале).
> 3. **Развилка:**
>    - **Всё зелёное И флоу реально покрыт фронтом end-to-end** → запиши доказательства (команда +
>      вывод + что именно прошло) в `docs/api-e2e-status.md`, статус домена → `verified`. **PR не нужен.**
>      Переходи к п.6.
>    - **Красное ИЛИ покрытие неполное** (нет браузерного прохода всего флоу, спека скипнулась,
>      найден баг API) → переходи к п.4 (executor).
> 4. **Executor (только при необходимости фикса/доработки).** Запусти скилл **`trendpulse-executor`**
>    в **planless-режиме — он предавторизован для этой кампании** (малые однозначные изменения:
>    дописать/починить Playwright-спеку для полного прохода флоу домена через фронт, или починить
>    найденный баг API). НЕ спрашивай про план — скоуп узкий и однозначный. Executor проведёт
>    do(TDD: спека RED→GREEN) → verify(G2: реальный прогон спеки против живого стека) →
>    review(adversarial, другой моделью) → security(5.5, если тронут auth/input/secrets) → ship.
>    Прайм-директива: **минимум файлов/строк**, diff строго в рамках домена. Блокирующие находки →
>    executor уходит в debug (макс 2 цикла); не решилось → HALT и вопрос.
> 5. **PR + подтверждение.** Стадия ship делает ветку `gsd/api-e2e-{domain}`, Conventional Commit,
>    `git push -u`, `gh pr create` с описанием: что проверено, реальные verify-доказательства
>    (вывод Playwright через фронт), артефакты. **Никогда не коммить/мёржи в `main` напрямую**
>    (bash-guard блокирует). Покажи пользователю PR + доказательства и **СПРОСИ подтверждение на
>    merge**. Без «подтверждаю» — заверши ход и жди (не планируй wakeup только ради ожидания).
> 6. **Закрытие домена.** Если был PR — после «подтверждаю»: `gh pr merge --squash --delete-branch`.
>    Затем статус домена в `docs/api-e2e-status.md` → `verified`, впиши evidence + ссылку на PR.
>    Краткий итог и переход к следующему домену.
>
> **ПРАВИЛА:** один домен за итерацию; verify-first (сначала прогон как есть, фикс только при
> необходимости); всё через фронт/nginx, НЕ внутренние юниты; среда — только через `make`, не raw
> `docker compose`; только PR-flow; реальное поведение, а не «билд зелёный»; любая неоднозначность,
> нехватка кред/конфига или нерешённый за 2 цикла debug → **HALT и вопрос**, не догадка.
>
> **ЗАВЕРШЕНИЕ:** когда все домены `verified` — выведи финальную сводку (таблица: домен · итог ·
> доказательство · PR/нет) и **заверши луп** (не планируй следующий wakeup). Подсвети, что осталось
> прод-/owner-only вне локального скоупа (live NOWPayments IPN, Google OAuth, Cloudflare
> email-routing, showcase) — это не провал, это другой уровень (см. `docs/full-system-test.md` §B/§C).

## Эталоны (откуда брать команды)

- Поднятие стека + гейт здоровья + запуск Playwright: `.github/workflows/main-integration.yml` (job `e2e`).
- Ручные пробы через nginx (auth/watchlist/health/GDPR): `docs/full-system-test.md` §A3.
- Email через Mailpit (verify/reset, чтение писем `GET :8025/api/v1/messages`): `frontend/tests/e2e/auth-verify-reset.spec.ts`.
- Поверхность роутов: `backend/src/api/main.py` (`v1_router.include_router(...)`).
