---
id: TASK-044
title: Showcase авто-постинг — топ-сигналы showcase-тенанта в публичный TG-канал (delay + CTA + анти-спам)
status: planned             # planned → in-progress → review → done
owner: backend
created: 2026-06-10
updated: 2026-06-10
baseline_commit: ""
branch: "gsd/phase-e3-showcase-autoposting"
tags: [epic-e3, backend, telegram, growth]
---

# TASK-044 — Showcase авто-постинг (Epic E3)

> Самый дешёвый канал привлечения — сам продукт. Beat-задача постит лучшие сигналы
> showcase-тенанта (TASK-039) в публичный TG-канал с задержкой 30–60 мин, каждый пост —
> живое доказательство («обнаружено в 14:02») + CTA-ссылка с utm. Анти-спам: score-порог +
> не чаще M постов/день. Позиционирование: «Узнай за 40 минут до того, как это станет
> мейнстримом».

## Context

Showcase-тенант: `api/trending/` (TASK-039) — системный юзер `showcase@internal`
(`showcase_user_email`), выборка топ-кластеров в `trending/service.py::get_trending`
(joins clusters←scores showcase-юзера, окно 24h, order viral_score DESC). Ops-бот:
`OPS_TELEGRAM_BOT_TOKEN`/`OPS_TELEGRAM_CHAT_ID` (TASK-035, config:
`ops_telegram_bot_token`) — для ПУБЛИЧНОГО канала нужен СВОЙ chat_id (канал), бот должен
быть админом канала. Beat: `backend/src/scheduler.py`. Отправка: переиспользовать
`TelegramBotBackend`-механику (`alerts/backends.py`) или httpx-вызов в новом модуле.
Дедуп постинга: нужна таблица `showcase_posts` (cluster_id → posted_at) — кластер постится
один раз.

## Goal

Beat-задача `showcase-autopost` (интервал `showcase_post_interval_seconds`, default 900):
берёт кластеры showcase-тенанта со score ≥ `showcase_post_min_score` (default 85), возрастом
≥ `showcase_post_delay_seconds` (default 2400 — «проверено временем») и ≤ окна 24h, ещё не
запощенные; постит лучший в канал `showcase_channel_chat_id` через `showcase_bot_token`
(fallback на ops-токен), с форматом «🔥 {title} · score {N} · обнаружено в {HH:MM} UTC» +
CTA-ссылка `{public_base_url}/?utm_source=tg_showcase&utm_campaign=autopost`. Не чаще
`showcase_posts_per_day_max` (default 8). Фиксирует пост в `showcase_posts`. DoD = AC.

## Discussion
- Q: Свой бот или ops-бот? → Decision: отдельные настройки `showcase_bot_token` /
  `showcase_channel_chat_id`; в MVP допустимо заполнить тем же токеном, что ops (бот один,
  чатов два) — но конфиг-ключи разные (зоны ответственности разойдутся).
- Q: Почему delay 40 мин, а не сразу? → Decision: (1) позиционирование «мы знали раньше» —
  пост со штампом обнаружения доказывает скорость задним числом; (2) не каннибализировать
  real-time ценность платного продукта (Free-задержка 30 мин — TASK-040 — должна быть
  меньше showcase-задержки, иначе канал лучше Free-плана). Инвариант:
  `showcase_post_delay_seconds > free_alert_delay_seconds`.
- Q: Что постим — кластер или пост-первоисточник? → Decision: кластер (title/topic/score/
  first_seen + каналы-источники count). Ссылки на оригинальные посты — нет (чужой контент,
  retention 48h, и юридически чище агрегат).
- Q: Идемпотентность? → Decision: UNIQUE(cluster_id) в showcase_posts + INSERT-first
  (как `_create_alert_idempotent`-паттерн): сначала фиксация, потом отправка; fail отправки →
  строка остаётся со status=pending, ретрай следующим тиком (статус-поле).

## Scope
- **Touch ONLY:**
  - `backend/migrations/versions/0015_showcase_posts.py` — **новая**: `showcase_posts`
    (id, cluster_id FK UNIQUE, status, posted_at, created_at).
  - `backend/src/storage/models/showcase_posts.py` — **новый**.
  - `backend/src/showcase/` — **новый модуль**: `selection.py` (кандидаты: score/age/окно/
    не запощен/дневной лимит — чистые функции), `formatting.py` (текст поста + CTA),
    `tasks.py` (beat task: select → fix → send → mark posted).
  - `backend/src/scheduler.py` — beat-запись.
  - `backend/src/config.py` — `showcase_bot_token` (secret), `showcase_channel_chat_id`,
    `showcase_post_interval_seconds` (900), `showcase_post_delay_seconds` (2400),
    `showcase_post_min_score` (85.0), `showcase_posts_per_day_max` (8).
  - `ops/ansible/roles/env/templates/sensitive.env.j2` + `vault` — новые ключи
    (vault_showcase_bot_token, vault_showcase_channel_chat_id; default '' → постинг off).
  - tests: `backend/tests/unit/showcase/` (**новые**).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** alerts-доставка юзерам, trending API-контракт (TASK-039), scorer.
- **Blast radius:** новый beat-тик (лёгкий SELECT); внешний вызов Bot API из beat-контекста —
  таймауты/ретраи обязательны; пустые настройки → задача no-op (как ops-alert TASK-035).

## Acceptance Criteria
- [ ] **AC1 — отбор кандидатов (failing-test anchor).** Селектор: score ≥ min, возраст ≥
  delay, внутри 24h-окна, не запощен, дневной лимит не исчерпан → один лучший кандидат;
  все отсечки покрыты. RED первым.
- [ ] **AC2 — пост уходит и фиксируется.** When тик с кандидатом, Then sendMessage в
  showcase-канал (мок Bot API: chat_id/текст с «обнаружено в HH:MM» + utm-CTA) и строка
  showcase_posts(status=posted).
- [ ] **AC3 — идемпотентность/ретрай.** Повторный тик не постит тот же кластер; fail
  отправки → status=pending → ретрай следующим тиком, без дублей при гонке.
- [ ] **AC4 — выключено по умолчанию.** Пустой token/chat_id → no-op + однократный
  log_event (как TASK-035-паттерн), beat не падает.
- [ ] **AC5 — анти-спам.** M постов сегодня → кандидаты не постятся до завтра (UTC-день).
- [ ] **AC6 — G2.** Живой стек: посев showcase-кластеров → реальный пост в тестовый канал
  (или мок при отсутствии кред); инвариант delay>free_delay проверен тестом конфига;
  `make ci-fast` зелёный.

## Plan
1. **RED:** unit selection (AC1/AC5) + tasks (AC2–AC4, мок Bot API/фейк-время).
2. Миграция 0015 + модель + config (+ инвариант-валидатор delay > free_alert_delay).
3. showcase/ модуль + scheduler.
4. env-шаблон + vault-ключи (default off).
5. GREEN + G2; tasks-index на ship.

## Invariants
- `showcase_post_delay_seconds > free_alert_delay_seconds` (валидатор Settings — канал не
  должен быть быстрее Free-плана).
- INSERT-first идемпотентность: кластер постится максимум один раз, при любой гонке.
- Пустые креды → полный no-op (deploy без витрины валиден).
- Никакого raw content постов-первоисточников — только агрегат кластера (compliance).

## Edge cases
- Кластер удалён ретенцией между select и send → skip, строка showcase_posts остаётся
  pending → janitor-очистка не нужна (старше 24h-окна не ретраится — отсечка возрастом).
- Bot API 429 (flood) → backoff-ретрай следующим тиком (не в цикле).
- Смена chat_id на лету → старые посты не трогаем.
- Два воркера/beat (не должно быть, но) → UNIQUE(cluster_id) держит.

## Test plan
- **unit:** selection (все отсечки + лимит/день), formatting (штамп времени, utm), task
  (мок Bot API: success/fail/429), config-инвариант.
- **integration:** тик на db_session: посев кластеров showcase-юзера → строки showcase_posts.
- **G2:** живой пост в тестовый канал (если креды есть) / мок.
- **security (5.5):** token не в логах/repr (паттерн TelegramTarget repr=False); CTA-ссылка
  не интерполирует user input.

## Checkpoints
current_step: 1
baseline_commit: ""
branch: "gsd/phase-e3-showcase-autoposting"
lock: ""
- [ ] 1 locate (scope + patterns + blast radius)
- [ ] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (secrets в env/vault — прогнать чеклист)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(planned 2026-06-10 — Epic E3. Deps: TASK-039 (showcase-тенант), TASK-035 (паттерн
ops-бота/no-op при пустых кредах). Ключевой продуктовый инвариант: канал медленнее
Free-плана, Free медленнее Pro — лестница ценности. Owner перед G2: создать публичный
канал + добавить бота админом + вписать chat_id в vault.)
