---
id: TASK-091
title: Twitter retweet/quote-граф + independence/collusion/botnet-сигнал (post-MVP)
status: deferred        # planned → in-progress → review → done; deferred = post-MVP
owner: backend
created: 2026-06-14
updated: 2026-06-14
baseline_commit: ""
branch: "task/091-twitter-virality-graph"
tags: [collector, twitter, scoring, anti-manipulation, graph, twitter-loop, phase-c, C7, post-mvp]
deps: [031, 089]
---

# TASK-091 — Twitter retweet/quote-граф + independence/collusion (ФАЗА C / C7, ОТЛОЖЕНО)

> Бриф: [../research/twitter-source-research-brief.md](../research/twitter-source-research-brief.md) §3,§5.
> **Статус deferred (post-MVP):** дорого по read-budget (эндпоинты retweeters/quotes = много
> чтений/твит при pay-per-use $0.005) и алгоритмически сложно. Делать ПОСЛЕ доказанного MVP-ингеста
> (TASK-031 + 089) и появления реального ключа/бюджета. Это и есть продуктовый моат (память
> `trendpulse-product-strategy`), но не блокер MVP.

## Goal (когда возьмут в работу)
Сетевой анти-накрут сигнал для Twitter: отличать ОРГАНИЧЕСКУЮ кросс-аккаунтную виральность от
накрученной (co-retweet-ring / бот-ферма), как наш TG independence/collusion-граф.

## Подход (из research §3)
- **Co-retweet network:** аккаунты, со-ретвитящие одни твиты в малых окнах → ребро коорд-графа.
- **Rapid-retweet:** всплеск ретвитов за секунды-минуты → activity-based след.
- **Account-age clustering:** ретвитеры, созданные в один промежуток → бот-ферма.
- **Co-hashtag:** частые совместные хэштеги.
- **Independence-score:** виральность по N **независимым** аккаунтам (не из одного co-retweet-
  сообщества) ранжируется выше; ring душится (ad-filter + анти-накрут).
- **Origin-tracing:** первый автор/первый ретвитер цепочки (`referenced_tweets`/conversation).
- Маппинг на наши механики — таблица в брифе §3.

## Предусловия для снятия с deferred
- MVP-ингест Twitter живой (031 + 089 verified live с реальным ключом).
- Решён read-budget для графовых эндпоинтов (отдельная стоимость; owner-решение).
- Решено где живёт граф-вычисление (отдельный Celery-таск/Beat; НЕ ломать scorer-контракт).

## Acceptance Criteria (черновик, уточнить при взятии)
- AC1: co-retweet/rapid-retweet граф строится по ограниченной выборке (в рамках read-budget).
- AC2: independence/collusion-score интегрирован в scoring БЕЗ слома платформо-независимого контракта.
- AC3: доказана дискриминация органика-vs-накрутка на размеченной/синтетической выборке (как T14/T15
  harness для TG-скоринга).

## Checkpoints
current_step: deferred
- [x] research (бриф ФАЗА B)
- [ ] (отложено до снятия предусловий)
