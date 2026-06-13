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
| 3 | email | auth-verify-reset.spec.ts | verified | auth-verify-reset.spec.ts **3/3 passed** (стабильно `--repeat-each=2` → 6/6) через nginx :80 + Mailpit :8025: register→письмо в Mailpit→`/auth/email/confirm`→`is_verified=true`; forgot→письмо→`/auth/password/reset`→логин новым паролем; Forgot-password ссылка. Потребовались фиксы готовности стека + корректности спеки (см. журнал) | [#130](https://github.com/BotNet1337/trend-pulse/pull/130) merged |
| 4 | watchlists | watchlists.spec.ts | verified | watchlists.spec.ts **8/8 passed** (2 прогона подряд зелёные) через nginx :80: pack subscribe→в списке, subscribe→unsubscribe, bad handle→field error, Free-лимит→402 upsell, дубль subscribe→идемпотентно (200, created=0), чужой/несуществующий id→not-found, гард неавторизованного→sign-in. (AC5 разово флакнул под параллелью 5 воркеров, стабилен при повторе) | — (PR не нужен) |
| 5 | alerts | alerts.spec.ts | verified | alerts.spec.ts **4/4 passed** через nginx (список, empty-state, no-auth→sign-in, detail not-found). Контракты через nginx с cookie: `GET /alerts`=200 `{items:[],next_cursor,history_unavailable}` (cursor-envelope ✓), unauth=401, `GET /feedback/<bad>`=400, `/feedback/`=404 (graceful HTML, не 500). Full feedback-tap + cursor-с-данными требуют засеянного доставленного алерта (scoring pipeline) — **вне скоупа кампании** (ML/Telegram), скип задокументирован в спеке + покрыт backend/unit | — (PR не нужен) |
| 6 | api-keys | api-keys.spec.ts | verified | api-keys.spec.ts **3/3 passed** (Free: section+CTA→/billing, server-gate POST→403, 5xx-resilience). Полный цикл через nginx с DB-seed Team-плана (`users.plan='team'` + subscriptions.expires_at future — документированный manual G2): create-Free→**403**, create-Team→**201** plaintext-ключ(однократно)+prefix+id, list→200(prefix, без plaintext), **auth-по-ключу** `GET /alerts` c `X-API-Key` без cookie→**200** (+history_unavailable:false=Team применился), плохой ключ→401, revoke→**204**, ревокнутый ключ→**401**, list-after-revoke→revoked_at выставлен | — (PR не нужен) |
| 7 | billing-account | billing-account.spec.ts | verified | billing-account.spec.ts **4/4 passed** (plan показан, invoice UI-флоу, delivery-config, GDPR delete). Контракт `POST /billing/invoice` через nginx (без live-IPN — NOWPAYMENTS_API_KEY реальный, живой инвойс не дёргаем): unauth→**401**, невалидный план→**422** (envelope `{plan: Input should be 'free','pro' or 'team'}`), пустое тело→422. GDPR `DELETE /account` — реальный e2e (не замокан): confirm-диалог→delete→redirect. Happy-path invoice в e2e намеренно замокан (live NOWPayments-вызов = граница скоупа) | — (PR не нужен) |
| 8 | delivery-config | billing-account.spec.ts | verified | покрыт в billing-account.spec.ts: `delivery_config_happy` (bot token + chat_id сохранены, токен замаскирован) + `invalid_webhook_rejected` (SSRF-bait URL → ошибка валидации) через фронт/nginx | — (PR не нужен) |
| 9 | referral | (nginx-проба) | verified | через nginx: `GET /referral/me` unauth→**401**, auth→**200** `{ref_code, referral_link:.../sign-up?ref=CODE, rewards:[]}`. Применение: регистрация с `referrer_code` валидного кода → `users.referred_by` = id реферера (проверено в БD: 69=69, write-once); bogus-код→**201** молча игнорируется (registration always succeeds). Награда ReferralReward — downstream при конверсии/оплате (вне скоупа) | — (PR не нужен) |
| 10 | packs-trending | (nginx-проба) | verified | через nginx: `GET /packs` auth→**200** (3 curated пака crypto-ru/tech-en/crypto-en, title/topic/channels_count), unauth→**401**; `GET /trending?pack=crypto-ru`→**200** `{items:[],warming_up:true}` (bootstrap/warming — trending-данные от pipeline вне скоупа), bad pack→**404**, limit>max→**422**. Subscribe-флоу пакетов покрыт watchlists.spec.ts | — (PR не нужен) |
| 11 | cases-feedback | (nginx-проба) | verified | через nginx: `GET /cases` (public, no auth)→**200** `{items:[]}` (контент proof-of-speed от showcase/pipeline вне скоупа), `top_n` валидация: valid→200, 0/негатив/huge→**422**; `GET /feedback/<bad>`→**400** (graceful HTML, no-oracle), `/feedback/`→**404**. Полный feedback round-trip требует HMAC-токена из доставленного алерта (pipeline вне скоупа) | — (PR не нужен) |
| 12 | email-unsubscribe | (nginx-проба) | verified | через nginx `GET /email/unsubscribe?token=`: no-token→**422**, bad-token→**400** (graceful «Invalid unsubscribe link»), **валидный JWT-токен (audience trendpulse:unsubscribe, сминчен тем же `generate_unsubscribe_token`, что в письме)→200** success HTML (Foresignal, «transactional emails not affected»); `users.lifecycle_emails_opt_out` **f→t** в БД; повторный хит→200 (идемпотентно) | — (PR не нужен) |
| 13 | ssr | ssr.spec.ts | verified | ssr.spec.ts **7/7 passed** через nginx: SSR-разметка на `/` и `/watchlists` (не пустой root div), `window.__INITIAL_STATE__` присутствует, authenticated SSR содержит user-данные, нет hydration-mismatch ошибок, unauth guarded-страница→sign-in (не сырой 401 JSON) | — (PR не нужен) |
| 14 | admin-metrics | admin-metrics.spec.ts | verified | admin-metrics.spec.ts **2/2 passed** через nginx: regular user→«Page not found» (no existence leak) + API 403, no-auth→sign-in с корректным `redirect`-параметром. **Найден+починен реальный баг**: AuthGuard зацикливал `redirect`-параметр (`?redirect=/auth/sign-in?redirect=…` ×N), захватывая sign-in-URL как новую цель → фикс: не редиректить на sign-in, если уже на sign-in. Регрессия: auth+smoke+ssr+watchlists+alerts+api-keys+billing = все зелёные | PR (ниже) |

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
