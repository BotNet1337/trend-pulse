# API E2E Status — полная проверка API через фронт

Источник истины по прогрессу автономной кампании (см. `docs/loop-api-e2e-verification.md`).
Каждый домен проверяется **end-to-end через реальный фронт** (nginx :80, Playwright-e2e) либо
ручными HTTP-пробами через nginx — НЕ внутренними pytest-юнитами.

Стек поднимается только через `make` (`make build` → `make up`). Гейт здоровья: `/api/health`==200,
`/api/ready`==200, Mailpit :8025 отвечает.

## Статусы

| # | domain | spec | status | evidence | pr |
|---|--------|------|--------|----------|----|
| 1 | health | smoke.spec.ts | verified | `/api/health`=200 `{"status":"ok"}`, `/api/ready`=200 `{"db":"ok","redis":"ok","celery":"ok"}`; smoke.spec.ts **5/5 passed** (бренд Foresignal, routing, 401-guard-redirect) через nginx :80 | — (PR не нужен) |
| 2 | auth | auth.spec.ts | verified | auth.spec.ts **7/7 passed** через nginx :80: register→login→logged-in, logout→401→guard-redirect, open-redirect игнор, неверный пароль (friendly, без enumeration), дубль email (generic, без disclosure), Google OAuth кнопка→`/api/auth/google/authorize` | — (PR не нужен) |
| 3 | email | auth-verify-reset.spec.ts | verified | auth-verify-reset.spec.ts **3/3 passed** (стабильно `--repeat-each=2` → 6/6) через nginx :80 + Mailpit :8025: register→письмо в Mailpit→`/auth/email/confirm`→`is_verified=true`; forgot→письмо→`/auth/password/reset`→логин новым паролем; Forgot-password ссылка. Потребовались фиксы готовности стека + корректности спеки (см. журнал) | PR `gsd/api-e2e-email` (pending merge) |
| 4 | watchlists | watchlists.spec.ts | pending | — | — |
| 5 | alerts | alerts.spec.ts | pending | — | — |
| 6 | api-keys | api-keys.spec.ts | pending | — | — |
| 7 | billing-account | billing-account.spec.ts | pending | — | — |
| 8 | delivery-config | (nginx-проба) | pending | — | — |
| 9 | referral | (nginx-проба) | pending | — | — |
| 10 | packs-trending | (nginx-проба) | pending | — | — |
| 11 | cases-feedback | (nginx-проба) | pending | — | — |
| 12 | email-unsubscribe | (nginx-проба) | pending | — | — |
| 13 | ssr | ssr.spec.ts | pending | — | — |
| 14 | admin-metrics | admin-metrics.spec.ts | pending | — | — |

Легенда статусов: `pending` (не начато) · `in_progress` · `verified` (зелёный прогон через фронт + evidence) · `blocked` (HALT — нужен ответ owner).

## Журнал итераций

### BOOTSTRAP (2026-06-13)
- Создан трекинг-док. Стек поднимается через `make build` → `make up`.
- env-файлы (`development/env/{deploy.env,sensitive.env}`) присутствуют, `ops/ansible/.vault-pass` есть.
- e2e-спеки присутствуют: smoke, auth, auth-verify-reset, watchlists, alerts, api-keys, billing-account, ssr, admin-metrics.

### Домен 1 health + 2 auth (2026-06-13) — verified, без PR
- `make build`+`make up` зелёные; гейт здоровья пройден (`/api/health`=200, `/api/ready`=200 db/redis/celery ok).
- smoke.spec.ts 5/5, auth.spec.ts 7/7 через nginx :80. Verify-first прошёл как есть — фиксы не потребовались, PR не нужен.

### Домен 3 email (2026-06-13) — verified, PR gsd/api-e2e-email
Verify-first: спека **скипалась** (Mailpit недоступен с хоста) → провал готовности. Цепочка диагностики и минимальных фиксов:
1. **Mailpit :8025 недоступен с хоста.** mailpit сидел только в сети `internal` (`internal: true`), что делало директиву `ports: 8025:8025` мёртвой. Фикс: добавлена dev-only bridge-сеть `mailpit_ui` (не internal) → порт публикуется на хост. SMTP api/worker→mailpit через `internal` сохранён.
2. **Письма не доходили** (api WARNING `email send failed`). Причина: `SMTP_USER=resend` (из ansible-managed `sensitive.env`) → бэкенд шлёт SMTP AUTH, а Mailpit отвергает AUTH на plaintext-соединении (`SMTPNotSupportedError`). Фикс: `MP_SMTP_AUTH_ACCEPT_ANY=true` + `MP_SMTP_AUTH_ALLOW_INSECURE=true` в mailpit.yml (dev-only sink, не в release/prod).
3. **Спека (4 фикса корректности, баги теста — не приложения):** (a) регекс `\?[^\s"<>]+token=` → `*` (приложение ставит `token` первым query-параметром); (b) декод `&amp;`→`&` у URL из HTML-тела письма (как почтовый клиент; иначе `email` парсится как `amp;email` и confirm-страница падает); (c) финальная проверка `is_verified` через `page.request.get('/api/v1/users/me')` (cookie сессии + nginx baseURL) с жёстким `expect(ok()).toBe(true)` вместо нового request-контекста без cookie, бившего в SPA-fallback при молчаливо пропускаемом `if(ok)`; (d) `waitForURL(/\/(?!auth)/)` (матчил `//` в `http://` мгновенно — no-op гонка) → предикат `(url)=>!url.pathname.startsWith('/auth/sign-in')` как в auth.spec.ts.
- Ревью другой моделью: APPROVED, 0 замечаний, ассерты усилены (не ослаблены), mailpit-флаги строго dev-only.
