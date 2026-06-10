---
id: TASK-060
title: Внешний uptime-мониторинг /api/ready + канал поддержки (support@ routing, витрины)
status: planned             # planned → in-progress → review → done
owner: infra
created: 2026-06-11
updated: 2026-06-11
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-uptime-support"
tags: [launch, ops, terraform, landing, frontend, p4]
---

# TASK-060 — Внешний uptime-мониторинг + канал поддержки

> Две дыры запуска, не закрытые ни одной задачей: (1) Sentry ловит ошибки приложения,
> self-alert (TASK-035) — здоровье пула, но **если VPS лёг целиком — никто не узнает**
> (P4: один VPS = одна точка отказа, прибора нет); (2) платящему клиенту **некуда
> написать** — `contactEmail` на лендинге = `support@trendpulse.app`, а наш домен —
> `foresignal.biz`: адрес ведёт на чужой/несуществующий домен, почтового маршрута нет.
> Чинится за день, без этого запускаться нельзя.

## Context

Probe готов: `GET /ready` (`api/routes/ops.py`) проверяет DB+Redis+Celery с таймаутами
(`readiness_check_timeout_seconds`), 200/503, без утечки деталей; публично доступен через
nginx как `/api/ready` (location `/api/` → backend). Внешнего наблюдателя НЕТ (ни TF-ресурса,
ни сервиса). Terraform после #50: `ops/terraform/modules/{cloudflare/{zone,email-routing,
dns-records},hetzner/{server,object-storage}}` + `environments/{org,prod}`; провайдеры
cloudflare ~>5.0, hcloud, minio. **Модуль `cloudflare/email-routing` уже есть** (org-env) —
маршрут support@ добавляется в существующий механизм. Витрины: `landing/public/config.json`
— `contactEmail: "support@trendpulse.app"` (битый домен foresignal.biz != trendpulse.app),
рядом `privacyEmail`/`abuseEmail`/`securityEmail`; `landing/src/pages/contact.tsx` —
статическая страница (рендерит email из config — форм/fetch нет, контракт task-018).
SPA: страницы account/billing без support-контакта. SMTP from: `noreply@…` (Resend, vault).

## Goal

После задачи: внешний монитор бьёт `https://<domain>/api/ready` каждые ≤5 мин и алертит
владельца (email + Telegram) при downtime/503; письмо на `support@foresignal.biz`
доставляется владельцу (Cloudflare Email Routing, IaC); лендинг и SPA показывают
рабочий support-адрес. DoD = AC.

## Discussion
<!-- durable record -->
- Q: Какой uptime-сервис? → A: бесплатный, с TG-алертом → Decision: **UptimeRobot free**
  (50 мониторов, 5-мин интервал, native Telegram-интеграция). Альтернативы (healthchecks.io
  — он про cron-пинги, не http-пробы; Better Stack — платный за TG) хуже под задачу.
- Q: Монитор — в Terraform? → A: нет, руками + документировано → Decision: официального
  TF-провайдера UptimeRobot нет, community-провайдер ради ОДНОГО монитора = новый
  supply-chain риск против правила «провайдеры pinned» — отказ. One-time ручная настройка,
  зафиксированная чек-листом в `docs/full-system-test.md` §C (как «секреты CD» в 057 —
  тоже one-time ручные). Пересмотр в пользу IaC — если мониторов станет >3.
- Q: Что мониторим — `/health` или `/ready`? → A: `/ready` → Decision: `/health` = liveness
  процесса (всегда ok пока жив), `/ready` = реальная готовность (DB/Redis/Celery) — для
  внешнего наблюдателя интересна именно она; keyword-check на тело ответа не нужен
  (статус-кода достаточно, 503 = алерт).
- Q: Не DoS-им ли себя проверками? → A: нет → Decision: 1 запрос/5 мин — ничтожно против
  глобального rate-limit 120/min; `/ready` дешёвый (SELECT 1 + PING + inspect с таймаутами).
- Q: support@ — routing или ящик? → A: routing → Decision: Cloudflare Email Routing
  (модуль уже в org-env) — форвард `support@foresignal.biz` → личный ящик владельца.
  Отдельный inbox/helpdesk = после первых десятков юзеров. `privacy@`/`abuse@`/`security@`
  — catch-all либо те же маршруты (одной правкой в том же модуле; до публичного запуска
  адреса в legal-страницах ОБЯЗАНЫ доставляться — урок task-018 про честность legal).
- Q: Куда положить support-контакт в SPA? → A: account-страница → Decision: одна строка
  «Need help? support@foresignal.biz» (mailto) на странице Account (рядом с
  delivery-config/danger-zone) — платящий ищет помощь там, где настройки. Без виджетов.
- Q: Зависимость от 057? → A: да → Decision: монитор и email-маршрут проверяются только
  на живом домене → финальные AC после деплоя 057; TF-правка и витрины готовятся сразу.

## Scope
> **terraform (org)** + **landing config** + **frontend (1 строка)** + **runbook-чеклист**.
> Probe-код backend НЕ трогаем.

- **Touch ONLY:**
  - `ops/terraform/environments/org/**` (+ модуль `cloudflare/email-routing` при
    необходимости параметризации) — маршрут `support@foresignal.biz` → ящик владельца
    (адрес назначения — tfvars, `sensitive=true` не требуется, но не хардкодим в модуле);
    `privacy@`/`abuse@`/`security@` — туда же.
  - `landing/public/config.json` — `contactEmail`, `privacyEmail`, `abuseEmail`,
    `securityEmail` → `…@foresignal.biz`.
  - `frontend/src/pages/account/**` — строка support-контакта (mailto; email — из
    конфиг-константы, не литерал в JSX-разметке среди логики).
  - `docs/full-system-test.md` §C — чек-лист «внешний мониторинг» (создание монитора
    UptimeRobot: URL, интервал, alert-контакты email+TG; периодическая проверка
    `systemctl`-эквивалент — раз в релиз).
  - `docs/architecture/pain-points.md` — P4 «сейчас»: дописать «внешний прибор есть
    (TASK-060)» (сам failover — по-прежнему «потом»).
  - `docs/tasks/tasks-index.md` — на ship.
- **Do NOT touch:** `api/routes/ops.py` (`/ready` работает), nginx (маршрут `/api/` уже
  отдаёт probe), Sentry (ошибки — его зона), backend вообще; `landing/src/pages/contact.tsx`
  (рендерит из config — код менять не надо, если email там не захардкожен — проверить).
- **Blast radius:** org-terraform (email-routing — аддитивный ресурс, `terraform plan`
  обязан показывать ТОЛЬКО add); витрины (строка/значения). Минимальный.

## Acceptance Criteria

- [ ] **AC1 — монитор живой.** Given монитор UptimeRobot на `https://<domain>/api/ready`
  (интервал ≤5 мин, контакты email+Telegram) When стек останавливается
  (`make -C release down` — контролируемый эксперимент при деплое) Then алерт приходит
  в TG ≤10 мин; When стек поднят Then приходит recovery.
- [ ] **AC2 — 503 ловится.** Given деградация зависимости (остановить redis-сервис на
  стенде прод-бандла) When `/ready` отдаёт 503 Then монитор считает down → алерт (это
  отличие от мониторинга «порт открыт»).
- [ ] **AC3 — support доставляется.** Given письмо с внешнего ящика на
  `support@foresignal.biz` When отправлено Then оказывается у владельца ≤5 мин;
  `terraform plan` после apply чистый (идемпотентность); privacy@/abuse@/security@ — тоже.
- [ ] **AC4 — витрины.** Лендинг (contact + legal-страницы) и SPA account показывают
  `support@foresignal.biz`; `grep -rn 'trendpulse.app'` по `landing/ frontend/` = 0.
- [ ] **AC5 — чек-лист воспроизводим.** §C-раздел проходится с нуля (свежая пара глаз):
  от логина в UptimeRobot до тестового алерта.

## Plan

1. TF: маршруты email-routing в org-env (`terraform plan` → только add → apply)
   — можно до 057 (зона уже делегирована, MX появятся сразу).
2. `landing/public/config.json` + проверка contact/legal-страниц (рендер из config);
   frontend account-строка + unit-снапшот при наличии соседних тестов страницы.
3. После 057 (домен отвечает): монитор UptimeRobot + alert-контакты (owner one-time,
   по чек-листу §C) → AC1/AC2 эксперименты на стенде/в окне деплоя.
4. AC3 письмо-прогон; pain-points P4 отметка.
5. Verify G2 = AC1–AC4 поведенческие прогоны; review; security 5.5 — skip-кандидат
  (нет auth/input/secret-кода; подтвердить на review: email владельца не светится в
  публичном config — на витринах только support@-адреса).

## Invariants

- `/ready` остаётся публичным и дешёвым (контракт для монитора; TASK-051 его не гейтит).
- Email-маршруты — ТОЛЬКО через terraform (org-env), не руками в дашборде Cloudflare
  (ADR-005-дисциплина: dashboard-drift запрещён).
- Личный ящик владельца не публикуется на витринах — только `support@foresignal.biz`.
- Legal-адреса (privacy/abuse/security) доставляются с момента публичного запуска
  (урок task-018: не публиковать мёртвые обещания).

## Edge cases

- UptimeRobot шлёт с пула IP — не добавлять его в какие-либо allowlist'ы nginx (нет их
  для `/api/ready`) — проверить, что 032 (будущий rate-limit) не накроет probe-путь:
  зафиксировать в доке 032-заметку «`/api/ready` вне жёстких лимитов».
- Cloudflare Email Routing требует MX/SPF на зоне — модуль email-routing их уже ставит
  (org-env живой) — `plan` покажет; конфликт с Resend-DNS (DKIM для исходящих) — разные
  записи, не пересекаются (Resend шлёт, CF принимает) — проверить план глазами.
- Монитор создан до 057 → красный с первого дня → создавать ПОСЛЕ деплоя (порядок в Plan).
- Owner сменит личный ящик → одна правка tfvars + apply (зафиксировано в §C).
- False-positive алерты при деплое (rolling-update держит api живым — 057 AC5; но
  миграции могут дать окно 503) → допустимо: алерт при деплое = сигнал смотреть на деплой;
  maintenance-паузы монитора не вводим (лишний процесс).

## Test plan

- Кода почти нет; проверки поведенческие: AC1 (down/recovery), AC2 (503-ветка),
  AC3 (почта), AC4 (grep витрин), `terraform plan/apply` идемпотентность.
- unit: только если у account-страницы есть существующие тесты — дополнить снапшот.
- security (5.5): skip-кандидат — подтвердить на review (нет новых поверхностей; личный
  email только в tfvars).

## Checkpoints

current_step: 3
baseline_commit: "8bc0b462d1d6f0a2468b7b3dc1cf50b22c7dc15e"
branch: "gsd/phase-uptime-support"
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TF + config + строка SPA + чек-лист)
- [ ] 4 verify (G2 — down/recovery + почта + витрины)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (skip-кандидат — подтвердить на review)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs: []

## Details

(planned 2026-06-11 из gap-анализа запуска: «если VPS лёг — никто не узнает» + «битый
support-адрес на лендинге». Решения: UptimeRobot вручную (нет официального TF-провайдера,
one-time как GitHub Secrets в 057), email — IaC через существующий cloudflare/email-routing.
Зависимости: 057 (живой домен) для финальных AC; TF и витрины — сразу. P4-прибор появляется;
сам failover (managed DB/второй узел) — «потом», когда выручка покроет.)
