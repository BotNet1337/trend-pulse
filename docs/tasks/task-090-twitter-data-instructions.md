---
id: TASK-090
title: Инструкция по данным Twitter/X (docs, рус) — доступ, ключ, env, эндпоинты, лимиты, расходы
status: done           # docs guide написан (docs/twitter-data-guide.md)
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: ""
branch: "task/090-twitter-data-instructions"
tags: [docs, twitter, ops, twitter-loop, phase-c, C6]
deps: [031]
---

# TASK-090 — Инструкция по данным Twitter/X (ФАЗА C / C6)

> Бриф: [../research/twitter-source-research-brief.md](../research/twitter-source-research-brief.md) §1,§4.

## Goal
Документ в `docs/` (на русском) для владельца: как получить нужные данные из Twitter/X — какой
доступ/тариф оформить, как выпустить ключ/токен, под каким именем env-переменной положить, какие
endpoint'ы/поля используем, лимиты/расходы, как добавить аккаунты в pack.

## Discussion (содержание документа)
- **Тариф/доступ:** X API v2; legacy Basic/$200·Pro/$5000 закрыты для новых → дефолт **pay-per-use**
  ($0.005/чтение, кап 2M/мес). Шаги регистрации developer-аккаунта X, создание проекта/приложения.
- **Ключ:** app-only **Bearer Token** (Project → Keys and tokens → Bearer Token). Положить в env как
  **`TWITTER_BEARER_TOKEN`** (на проде — vault `vault_twitter_bearer_token` → group_vars; формат как
  существующие секреты). Никогда в код/логи.
- **Эндпоинты/поля:** `GET /2/users/by/username/:u` (id+проверка), `GET /2/users/:id/tweets`
  (`since_id`/`start_time`, `tweet.fields=public_metrics,created_at,referenced_tweets`, `max_results`).
  Маппинг полей → `PostMetrics` (like→reactions, retweet→forwards, impression→views, остальное extra).
- **Лимиты/расходы:** read-budget; дефолтный кадэнс 15 мин; `MAX_TWITTER_READS_PER_MONTH`; оценка
  $/мес при N аккаунтах; как поднять/опустить кап; что происходит при превышении (no-op + ops-алерт).
- **Как добавить аккаунты в pack:** где правится `api/packs/data.py` (slug `crypto-twitter`),
  формат handle (username без '@', 1-15), что каждый прогоняется через `validate_ref`.

## Acceptance Criteria
- AC1: `docs/twitter-data-guide.md` (рус) покрывает: тариф/регистрацию, выпуск Bearer, env-имя
  (`TWITTER_BEARER_TOKEN`) + vault-путь, эндпоинты/поля, лимиты/расходы/кап, добавление аккаунтов.
- AC2: согласовано с реальным кодом (config-имя, эндпоинты, маппинг — те же, что в TASK-031/089).
- AC3: MANUAL-TODO §X/Twitter дополнен ссылкой на гайд + что именно сделать владельцу (оформить
  доступ, положить `TWITTER_BEARER_TOKEN`).

## Checkpoints
current_step: plan
- [x] plan (this doc)
- [ ] do (написать docs)
- [ ] verify (ссылки/согласованность)
- [ ] ship (PR)
