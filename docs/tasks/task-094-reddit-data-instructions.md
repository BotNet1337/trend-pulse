---
id: TASK-094
title: Инструкция по данным Reddit (docs, рус) — доступ, OAuth2-ключ, env, эндпоинты, лимиты, добавление сабреддитов
status: planned        # docs guide
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: "8debda0b863501cdf92fea2d1105264f73ca98bb"
branch: "gsd/phase-094-reddit-data-instructions"
tags: [docs, reddit, ops, reddit-loop, phase-r, R3]
deps: [092]
---

# TASK-094 — Инструкция по данным Reddit (reddit-loop ФАЗА R / R3)

> **Зеркало [TASK-090](./task-090-twitter-data-instructions.md)** (Twitter owner-инструкция) для Reddit.

## Goal
Документ `docs/reddit-data-guide.md` (на русском) для владельца: как получить данные из Reddit — какой
доступ оформить, как выпустить client_id/secret, под какими env-именами положить, какие эндпоинты/поля
используем, лимиты, как добавить сабреддиты в pack, что произойдёт после установки ключа.

## Discussion (содержание документа)
- **Доступ/тариф:** Reddit OAuth2 **application-only** (тип app «script» или «web»), read-only публичные
  данные — **бесплатно** (в отличие от Twitter pay-per-use). Шаги: создать Reddit app на
  https://www.reddit.com/prefs/apps (тип script/web), получить `client_id` (под названием app) и `secret`.
- **Ключ/env:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` (+ optional
  `REDDIT_API_BASE_URL`). На проде — Ansible vault (`vault_reddit_*` → group_vars; формат как существующие
  секреты, по образцу `vault_twitter_bearer_token`). Reddit **требует уникальный `User-Agent`** (формат
  `platform:appname:version (by /u/username)`). Никогда в код/логи; маскировать.
- **OAuth2 flow:** `POST https://www.reddit.com/api/v1/access_token` (`grant_type=client_credentials`,
  Basic-auth `client_id:client_secret`, заголовок `User-Agent`) → `access_token` (TTL ~1ч, рефреш по
  истечении); API после auth — `https://oauth.reddit.com`.
- **Эндпоинты/поля:** `GET /r/{sub}/about` (validate_ref — сабреддит существует/публичный),
  `GET /r/{sub}/new?limit=N` (свежие посты, фильтр `created_utc >= since`). Маппинг полей → `PostMetrics`:
  `score`→reactions, `num_crossposts`→forwards, `views`→0 (Reddit не отдаёт просмотры), остальное
  (`num_comments`/`upvote_ratio`/`total_awards_received`) → extra.
- **Лимиты:** free OAuth ~100 QPM; **нет per-read цены** → жёсткого месячного read-budget нет, только
  rate-limit-aware backoff (`X-Ratelimit-Remaining`/`Reset`, 429-backoff). Дефолтный кадэнс 5 мин
  (`REDDIT_COLLECT_INTERVAL_SECONDS=300`), `max_results`=50 на тик.
- **Как добавить сабреддиты в pack:** где правится `api/packs/data.py` (slug `crypto-reddit`), формат handle
  (сабреддит без `r/`, 3–21 `[A-Za-z0-9_]`), что каждый прогоняется через `validate_ref`.
- **Что произойдёт после установки ключа:** воркер при рестарте строит `RedditCollector` (registry.get
  REDDIT); source-agnostic `collect_tick` читает Reddit-рефы из watchlist'ов/паков; Reddit-посты проходят
  тот же pipeline (dedup→normalize→embed→cluster→score) → `viral_score` наравне с TG/Twitter; кросс-
  источниковая кластеризация объединяет одну тему из TG, Twitter и Reddit. (Это и проверяет ФАЗА 2.)

## Acceptance Criteria
- AC1: `docs/reddit-data-guide.md` (рус) покрывает: доступ/регистрацию app, выпуск client_id/secret,
  env-имена (`REDDIT_CLIENT_ID`/`SECRET`/`USER_AGENT`) + vault-путь, OAuth2-flow, эндпоинты/поля, лимиты,
  добавление сабреддитов, что произойдёт после установки ключа.
- AC2: согласовано с реальным кодом (config-имена, эндпоинты, маппинг, кадэнс — те же, что в TASK-092/093).
- AC3: MANUAL-TODO §Reddit дополнен ссылкой на гайд + что именно сделать владельцу (оформить app, положить
  `REDDIT_CLIENT_ID`/`SECRET`/`USER_AGENT` в env/vault).

## Scope
- **Touch ONLY:** `docs/reddit-data-guide.md` (новый); MANUAL-TODO-док (ссылка + owner-шаги);
  `docs/tasks/tasks-index.md` на ship.
- **Do NOT touch:** код (`backend/**`), pipeline/scorer, `_bmad/.claude/landing`.
- **Blast radius:** только docs.

## Verify
- ссылки/согласованность с кодом (config-имена, эндпоинты, маппинг, кадэнс из TASK-092/093 совпадают);
  `make ci-fast` (docs-only — без тестов кода) либо markdown-lint, ядро не тронуто.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: "8debda0b863501cdf92fea2d1105264f73ca98bb"
branch: "gsd/phase-094-reddit-data-instructions"
lock: ""
- [x] 1 locate (scope + patterns)
- [x] 2 plan (this doc, зеркало TASK-090)
- [ ] 3 do (написать docs)
- [ ] 4 verify (ссылки/согласованность)
- [ ] 5 review (auto)
- [ ] 5.5 security (n/a — docs)
- [ ] 6 ship (PR, squash-merged)
- [ ] 7 learnings (auto)
debug_runs: []

## Details
(initial — калька [TASK-090](./task-090-twitter-data-instructions.md): owner-гайд по данным. Зависит от
TASK-092 (config-имена/эндпоинты/маппинг — источник истины). Reddit OAuth2 application-only, бесплатно,
нет read-budget. Run в worktree `apps/trendPulse-reddit`.)
