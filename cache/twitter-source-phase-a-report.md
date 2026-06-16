# ФАЗА A — отчёт верификации prod (2026-06-14, итерация 2)

Прод: **https://foresignal.biz** (landing) + **https://app.foresignal.biz** (SPA/API). Хост
`trendpulse-prod` (167.233.81.243), docker swarm.

## 1. Здоровье prod — ✅ GREEN

| Проверка | Результат |
|---|---|
| Сервисы | **9/9 up** (api·beat·frontend·landing·nginx·postgres·redis·templates·worker), healthcheck'и healthy; nginx up 26h, postgres up 2h, redis up 26h |
| `/api/ready` (внешний HTTPS) | **200** |
| Свежий ingest | **18 постов за 2ч**, newest `posted_at=2026-06-14 13:01:59Z`; `collect_tick` тикает ~60с (43 refs), collected posts>0 |
| viral_score | **93 скоров, ВСЕ >0**, max **44.20**, выборка 21.5/7.7/5.1/9.2/13.5 — осмысленное распределение (TASK-084/086 в проде) |
| Redis | used **52.67M / 224M**, policy `noeviction`, **evicted_keys=0** — без OOM (TASK-076) |
| TG session-пул | `pool_health`: size=2, cooling=0, **healthy=2**, target=1, degraded=false |
| Auth-ошибки (24h) | **0** AuthKey/auth_error/quarantine — спама нет; фикс ФАЗЫ 0 = латентный страховочный механизм |
| Cert SAN | один серт `CN=foresignal.biz`, **SAN = app.foresignal.biz + foresignal.biz** на обоих доменах |

Прод здоров. Прочих prod-дефектов не выявлено.

## 2. MCP + REST `/v1/signals` (фича T7) — ⚠️ НЕ ЗАДЕПЛОЕНО (премиса ФАЗЫ A неверна)

**Факт:** живой `GET https://app.foresignal.biz/api/v1/signals` → **404** (JSON-envelope приложения,
т.е. nginx ДОХОДИТ до бэкенда, но роут отсутствует). Live OpenAPI отдаёт 0 путей (SWAGGER гейтнут
в проде, TASK-019). В `api/main.py` на `main` **нет** `signals_router`, нет MCP.

**Где T7 на самом деле:** на НЕ-смерженной ветке `signal/t7-public-api-mcp` (commit `7c3fa36`
`feat(api): public signals REST endpoint + MCP server (T7)`), которая стоит поверх всей
НЕ-смерженной цепочки `signal/t1..t6` (adshill-filter, headline-score, source-attribution,
actionable-payload). Не ancestor для `main`.

**Что именно построено в T7 (по диффу 7c3fa36, 8 файлов, +338):**
- `GET /v1/signals?limit=` — auth-gated, отдаёт recent `SignalPayload` (headline_score, signal_kind,
  category, origin, total vs INDEPENDENT channels, lead-time, narrative).
- `api/signals/mcp.py` — **stdio JSON-RPC MCP-сервер** (`python -m api.signals.mcp`, без внешней
  mcp-зависимости), tool `list_signals`. **Это НЕ HTTP/SSE** → «MCP через nginx» к этой реализации
  НЕ применимо.
- Источник по умолчанию — `EmptySignalSource` (отдаёт пусто); DB-backed source («T6b») НЕ подключён.
- 7 unit-тестов, ruff+mypy clean.

**Вывод:** критерий ФАЗЫ A «живой MCP-вызов через nginx» НЕ выполним против текущей реальности:
фича не в проде, MCP — stdio (не сетевой), данные пустые. Продакшнизация T7 = многошаговый
feature-эпик (мердж signal-цепочки t1-t7 + подключение DB-source + перевод MCP на HTTP/SSE + nginx
+ деплой), а не «верификация». Это hard-to-reverse product-surface решение, осознанно оставленное
на ветках.

**РЕШЕНИЕ (automode default):** НЕ мерджить эпик автономно. Завести трекинг-задачу **TASK-088**
(owner-decision) с рекомендованным путём и записать в MANUAL-TODO. ФАЗА A закрыта по
верифицируемой части (prod health GREEN); пункт T7/MCP — owner-blocked. Продолжаю на главную
цель цикла — **ФАЗА B (Twitter source)**.

**Рекомендация владельцу:** если T7 нужен в проде — это отдельный эпик; минимальный осмысленный
live = (1) мердж signal/t1-t7 в main аккуратной серией, (2) подключить DB-backed SignalSource,
(3) для агентского доступа либо обернуть MCP в HTTP/SSE (`mcp` SDK streamable-http) + nginx
(`proxy_buffering off`, длинный `proxy_read_timeout`), либо оставить stdio и документировать
локальный запуск. Без (2) endpoint отдаёт пусто.
