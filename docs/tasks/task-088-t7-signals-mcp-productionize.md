---
id: TASK-088
title: Продакшнизация T7 — публичный /v1/signals + MCP (мердж signal-эпика, DB-source, HTTP-MCP)
status: blocked         # owner-decision: мерджить ли signal-эпик в прод
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: "9c77dd5"
branch: "signal/t7-public-api-mcp (не смержена)"
tags: [api, signals, mcp, public-api, T7, owner-decision, phase-a-gap]
---

# TASK-088 — Продакшнизация T7 (signals REST + MCP)

> Обнаружено в ФАЗЕ A (см. `cache/twitter-source-phase-a-report.md`): премиса «T7 задеплоен
> (PR #135–#145)» НЕВЕРНА. `GET /api/v1/signals` в проде → 404; в `api/main.py` на `main` нет
> `signals_router`/MCP. T7 живёт на НЕ-смерженной `signal/t7-public-api-mcp` (commit `7c3fa36`),
> поверх НЕ-смерженной цепочки `signal/t1..t6`.

## Goal
Сделать публичный signals-доступ реально живым в проде ЛИБО осознанно отложить. Это feature-эпик,
не surgical-задача и не «верификация».

## Discussion (automode default зафиксирован)
- Q: мерджить ли эпик автономно в рамках twitter-loop? → A: **НЕТ.** Hard-to-reverse
  product-surface (новый публичный API + auth-gating + вся signal-quality цепочка t1-t6, осознанно
  оставленная на ветках). Требует owner-решения. Цикл не блокируется этим — главная цель цикла
  Twitter-source (ФАЗА B/C) идёт дальше.
- Что построено в T7 (commit 7c3fa36, 8 файлов, +338): `GET /v1/signals?limit=` (auth-gated,
  `SignalPayload`); `api/signals/mcp.py` — **stdio** JSON-RPC MCP (`python -m api.signals.mcp`,
  tool `list_signals`, без внешней mcp-deps); default `EmptySignalSource` (пусто); DB-source («T6b»)
  не подключён; 7 unit-тестов, ruff+mypy clean.
- Ключевые расхождения с премисой ФАЗЫ A:
  1. MCP — **stdio, не HTTP/SSE** → «MCP через nginx» неприменимо как есть.
  2. Источник пустой → even-if-deployed endpoint отдаёт `[]`.
  3. T7 зависит от мерджа signal/t1-t6 (scorer-эпик качества сигнала).

## Рекомендованный путь (если owner решит продакшнизировать)
1. Аккуратный мердж серии `signal/t1 → … → t7` в `main` (по одной, с прогоном `make ci`),
   ЛИБО cherry-pick минимального набора, если t7 компилируется без t1-t6 (проверить импорты
   `api/signals/{service,schemas}.py`).
2. Подключить DB-backed `SignalSource` (заменить `EmptySignalSource` через dependency override),
   иначе `/v1/signals` пуст.
3. Агентский доступ: либо обернуть MCP в HTTP/SSE (официальный `mcp` SDK streamable-http) и
   завести nginx-маршрут (`proxy_buffering off`, длинный `proxy_read_timeout`), либо оставить
   stdio + задокументировать локальный запуск (тогда «через nginx» снимается из критерия).
4. nginx-маршрут `/api/v1/signals` уже покрыт общим `/api/` (бэкенд доходит — 404 от приложения,
   не от nginx), отдельный фикс не нужен; нужен сам роут в приложении.
5. Деплой + живой end-to-end чек.

## Acceptance (когда разблокируют)
- AC1: `GET https://app.foresignal.biz/api/v1/signals` (с валидным ключом) → 200 + непустой JSON.
- AC2: агентский MCP-доступ к `list_signals` работает (HTTP/SSE через nginx ИЛИ stdio локально —
  по решению owner), tool отдаёт те же сигналы.
- AC3: тесты зелёные; signal-эпик в main не ломает существующие роуты/CI.

## Status
**BLOCKED на owner-decision.** Записано в MANUAL-TODO. Не блокирует ФАЗУ B/C.
