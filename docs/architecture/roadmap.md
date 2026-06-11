# TrendPulse — Roadmap

Источник истины по продукту: [`../product/overview.md`](../product/overview.md).
Эпики текущей волны: [`../product/epics/`](../product/epics/README.md).
Болевые точки архитектуры: [`pain-points.md`](./pain-points.md).
Задачи: [`../tasks/tasks-index.md`](../tasks/tasks-index.md).

## Состояние (2026-06-09)

| Эпик | Поток | Состояние |
|------|-------|-----------|
| **A** | Backend core (task-001…012) | ✅ done |
| **B** | Landing (task-018) | ✅ done |
| **C** | Frontend App SPA (task-013…017) | ✅ done |
| **D** | Hardening & growth (task-019…028) | ✅ done (028 смержен PR #33); хвост 029–033 перераспределён (ниже) |
| **E** | **Path to revenue** (task-034…055) | ⏳ текущая волна — детали в [`../product/epics/`](../product/epics/README.md) |

**Сдвиг фокуса:** эпики A–D строили систему. Волна E строит «последнюю милю» до пользователя и денег:
все 33 закрытые задачи — про систему, ни одна — про человека, который платит. Цель волны:
**первый платящий → $2k MRR**.

## Epic E — Path to revenue

Подэпики (полные планы — в `docs/product/epics/`):

| Подэпик | Суть | Задачи | Когда |
|---------|------|--------|-------|
| [E0](../product/epics/epic-e0-survival-ops.md) | Выживание: Hetzner-бакет (056), бэкапы, пул, latency-метрика, embed-кэш | 056, 034–037 — **done** | done (2026-06-10) |
| [E1](../product/epics/epic-e1-first-value.md) | Первая польза за 30 секунд: паки, instant value, free-delay | 038–040 — **done** | done (2026-06-10) |
| [E2](../product/epics/epic-e2-signal-quality.md) | Качество сигнала: историч. baseline, 👍/👎, адаптивный порог | 041–043 — **done** | done (2026-06-10/11) |
| [E3](../product/epics/epic-e3-showcase-channel.md) | Витрина-канал: авто-постинг, proof-of-speed, рефералка | 044–046 — **done** | done (2026-06-11) |
| [E4](../product/epics/epic-e4-frictionless-money.md) | Деньги без трения: год/квартал, one-click renewal, grace | 047–048 | после E1–E3 |
| [E5](../product/epics/epic-e5-pricing-packaging.md) | Цены и упаковка: Pro $29 / Trader $99, Free=воронка | 049 (+030) — **done** | done (2026-06-11) |
| [E6](../product/epics/epic-e6-business-metrics.md) | Бизнес-метрики: воронка, конверсия, MRR-дашборд | 050 — **done**; 051 in-progress | сейчас |
| [E7](../product/epics/epic-e7-cost-and-scale.md) | Масштаб: глобальный pipeline, событийный скоринг, fallback-источник | 052–055 | после E6 |
| [E8](../product/epics/epic-e8-new-sources-markets.md) | Новые источники/рынки: Twitter (031), B2B fiat, white-label | 031 + future | после $2k MRR |

**Критический путь до первого доллара:**
056 (Hetzner-бакет) → 034 (бэкапы) → 038 (packs) → 039 (instant value) → 040 (free-delay) → 042 (👍/👎) → 044 (витрина) → 049 (цены).
E0–E3 параллелятся; включать платное продвижение раньше E1–E3 — бессмысленно.

## Хвост Epic D

- task-029 SSR — in-progress (взят до волны E); после него фокус строго на E0/E1 — деньги важнее DX.
- task-030 API hardening — **done** (2026-06-11, ADR-007: error-envelope + /api/v1; предпосылка продажи API-тарифа закрыта).
- task-031 Twitter — триггер $2k MRR (E8).
- task-032 security (at-rest, P5-навсегда) — перед публичным запуском / первым B2B.
- task-033 GDPR export — compliance-бэклог.

## Distribution (future)

Боты из `botnet/apps/*` публикуются как OCI-артефакты через ORAS в `botnet/release` (один VPS-деплой).
Не сейчас; образы держим переносимыми. См. [build-and-release.md](./build-and-release.md), [ADR-006](./adr-006-packaging-and-release.md).

## Принципы планирования

- Каждая backend-задача: TDD-якорь, реальная behavioral-проверка (G2), `trendpulse-security`
  где трогаются auth/secrets/OAuth/input/raw SQL.
- Source-agnostic ядро (ADR-001); провайдеры за абстракциями (`SourceCollector`, `PaymentGateway`).
- Окружение — только через root `Makefile`; сети сегментированы; секреты из Ansible (ADR-005).
- **Новое для волны E:** у каждой продуктовой задачи есть метрика успеха (E6-воронка) — «сделано» ≠ «работает на деньги».
