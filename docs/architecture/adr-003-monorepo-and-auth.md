# ADR-003 — Monorepo layout & authentication

- Status: **Accepted**
- Date: 2026-06-08
- Context: high-level-architecture.md, overview §3

## Context

Три приложения (backend, landing, frontend) живут в одном репо `apps/trendPulse`. Нужен внятный layout и решение по auth, общее для backend и frontend.

## Decision

### Layout (3 apps in `apps/trendPulse/`)

```
apps/trendPulse/
├── backend/      # Python: FastAPI + Celery (src-layout пакет trendpulse)
├── landing/      # React + Vite — маркетинговый лендинг (SSG/static)
├── frontend/     # Vite + React SPA — дашборд
├── development/  # Makefile + docker-compose — единый оркестратор всех apps
└── docs/         # vault
```

- Каждое приложение — самодостаточное (свой `pyproject.toml` / `package.json`, свой Dockerfile).
- `development/Makefile` — единственная точка входа: backend-таргеты сейчас, `landing-*`/`frontend-*` добавляются в их эпиках.
- Frontend ↔ backend общаются по REST (FastAPI), типы запросов/ответов — из OpenAPI-схемы FastAPI (генерация клиента опционально).

### Auth — готовая библиотека (fastapi-users), per overview §3

- **Решение:** НЕ катаем свой auth — берём **`fastapi-users`** (+ `fastapi-users-db-sqlalchemy` под нашу БД, `httpx-oauth` для Google). Даёт из коробки: регистрацию, логин, хэш пароля (argon2/passlib), JWT/cookie-стратегии, OAuth (Google), сброс/верификацию.
- **Метод:** email+пароль **и** Google OAuth (через `httpx-oauth` GoogleOAuth2). Без внешнего SaaS-провайдера (Clerk/Auth0) — данные у нас.
- **Сессии:** JWT access (короткий) + refresh; для SPA — httpOnly cookie-транспорт fastapi-users.
- **Авторизация:** пользовательские эндпоинты за зависимостью `current_user` от fastapi-users; тенант-скоуп по `user_id` из токена (ADR-002).
- **Plan-gating:** лимиты тарифа проверяются в одном месте (`billing/limits`, ADR-004), не размазаны по роутам.
- **Env/секреты:** JWT secret, Google client id/secret — из `sensitive.env` (ADR-005), не в коде.

> Почему библиотека: auth — частый источник уязвимостей; зрелая либа закрывает хэширование/ротацию/OAuth-flow корректно. Стадия `trendpulse-security` всё равно обязательна на task-003.

## Consequences

- (+) Чёткое разделение трёх приложений, общий оркестратор; деплой независим.
- (+) Auth полностью наш — нет vendor-зависимости/стоимости на MVP; контроль над JWT/OAuth.
- (−) Сами отвечаем за безопасность auth (хэширование, refresh-ротация, OAuth callback/PKCE) → стадия `trendpulse-security` обязательна на этих задачах.
- (−) Смешанный toolchain (Python + Node) в одном репо — изолируем по папкам и make-таргетам.
- Влияет на задачи: **task-003** (auth), **task-010** (billing/limits), эпики B/C (frontend/landing scaffold).
