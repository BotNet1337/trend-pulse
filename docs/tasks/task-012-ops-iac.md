---
id: TASK-012
title: Ops / IaC — Terraform (внешние сервисы) + Ansible (prod-настройки/дефолты + доставка секретов)
status: done        # planned → in-progress → review → done
owner: infra
created: 2026-06-08
updated: 2026-06-08
baseline_commit: "40c932904e13d93d4ccd818f5b247e8f1abf5c20"
branch: "gsd/phase-012-ops-iac"
tags: [ops, iac, terraform, ansible, secrets]
---

# TASK-012 — Ops / IaC (Terraform · Ansible · доставка секретов)

> Реализовать `ops/` как IaC по [ADR-005](../architecture/adr-005-infra-provisioning-and-secrets.md): `ops/terraform/` провижинит внешние сервисы (DNS, VPS/провайдер, firewall/edge, объектное хранилище при необходимости), `ops/ansible/` готовит VPS (docker/compose, деплой стека) и является **единственным источником истины по env** — рендерит `deploy.env` (несекретные дефолты) и расшифровывает `sensitive.env` (секреты) и локально, и на prod. `make ansible-unpack` материализует оба файла в `development/env/`.

## Context

Проект — TrendPulse (см. [`../product/overview.md`](../product/overview.md)): FastAPI · Celery+Redis · PostgreSQL+pgvector · Telethon, за nginx-edge. Скелет `ops/` создан в [task-001](./task-001-dev-environment.md) как заготовка; **эта задача его наполняет**.

[ADR-005 §5](../architecture/adr-005-infra-provisioning-and-secrets.md) фиксирует раскладку `ops/`: `ops/terraform/` — внешние сервисы через IaC; `ops/ansible/` — playbooks, `group_vars` (prod settings + defaults), `vault` (секреты), inventory; доставляет `deploy.env`/`sensitive.env` на VPS и локально. [ADR-005 §4](../architecture/adr-005-infra-provisioning-and-secrets.md) объявляет **Ansible единственным источником истины** по переменным: `deploy.env` рендерится из `group_vars/*`, `sensitive.env` расшифровывается из ansible-vault — обе материализации идут через `make ansible-unpack` в `development/env/`.

Сетевой контур задаётся в [network-design.md](../architecture/network-design.md): наружу торчит только nginx-edge (80/443), всё прочее портов не публикует. Firewall в Terraform обязан зеркалить это: открыты **только** 443 (+80 redirect), остальное закрыто.

Конвенции: [`../CONVENTIONS.md`](../CONVENTIONS.md). Точка входа — root `apps/trendPulse/Makefile` (`make …`), не raw `docker compose`/`terraform`/`ansible-playbook`.

## Goal

Инженер с нуля делает `make ansible-unpack` → получает непустые `development/env/{deploy.env,sensitive.env}`, отрендеренные из Ansible (`group_vars` + расшифрованный vault), и `make up` поднимается на этих переменных. `terraform validate` на `ops/terraform` чист; `ansible-lint` и `ansible-playbook --check` (dry-run) проходят. В git нет ни одного plaintext-секрета (`sensitive.env` гитигнорится, vault зашифрован). Все действия — через `make`. DoD ниже.

## Discussion
<!-- durable record of clarifications. Решения приняты по дефолтам ADR-005; все обратимы. -->
- Q: Что управляет внешними ресурсами, а что хостом? → A: **Terraform — внешние сервисы** (DNS, VPS/провайдер, firewall/edge, объектное хранилище), **Ansible — настройка хоста** (docker/compose, деплой стека, доставка env) → Decision: чёткая граница «provision (TF) → configure (Ansible)» (rationale: ADR-005 §5; TF держит cloud-state, Ansible — состояние внутри VPS).
- Q: Источник env-переменных? → A: **Ansible — единственный источник истины** (и локально, и prod) → Decision: `deploy.env` ← рендер из `group_vars/*` (несекретное), `sensitive.env` ← расшифровка `vault` (секреты); оба материализуются `make ansible-unpack` в `development/env/` (rationale: ADR-005 §4 — один источник, нет дрейфа между локалью и prod).
- Q: Где prod-настройки и дефолты? → A: **в Ansible `group_vars`**, не в коде/compose → Decision: несекретные дефолты (имена БД, порты, имена сетей, URL-шаблоны, фичефлаги) живут в `group_vars/all.yml`; среды (`group_vars/prod.yml`, при необходимости `dev`) переопределяют (rationale: ADR-005 §4 — `deploy.env` = несекретные дефолты, рендерится отсюда).
- Q: Как хранятся секреты? → A: **ansible-vault** (зашифрованный файл), пароль vault — вне репо → Decision: `vault/sensitive.vault.yml` (encrypted), `--vault-password-file` из env/локального файла вне git; в git только зашифрованный blob (rationale: ADR-005 §4 — `sensitive.env` гитигнор, прилетает из Ansible; ничего открытого не коммитим).
- Q: Terraform state? → A: remote backend, не local → Decision: backend-блок (S3-совместимый/провайдерский remote) с lock; чувствительные backend-креды — через env/`-backend-config`, не в `.tf` (rationale: воспроизводимость + защита от потери/конфликта state; секретов в `.tf` нет — ADR-005, CONVENTIONS).
- Q: Секреты в Terraform-файлах? → A: **нет** → Decision: TF-переменные (`variable {}`) + `*.tfvars` вне git / env `TF_VAR_*`; чувствительные помечены `sensitive = true` (rationale: CONVENTIONS «secrets via env/secret-manager only»; никаких хардкодов).
- Q: Firewall-правила? → A: зеркалить network-design → Decision: открыты только 443 и 80 (redirect→443), весь прочий ingress закрыт; SSH — ограничен (allowlist/ключи) (rationale: network-design «edge — единственная точка входа», least-privilege).
- Q: Объектное хранилище? → A: только если реально нужно (бэкапы/артефакты) → Decision: модуль/ресурс под object storage добавляется при появлении потребности; на старте опционален, контракт переменных заложен (rationale: не вводить лишние ресурсы преждевременно).

## Scope
> **Раскладка:** эта задача трогает **только `ops/`** (Terraform + Ansible) и проводку `make ansible-unpack` (таргет объявлен в root `Makefile` в task-001 — здесь наполняется реализацией). Backend-код, compose-сервисы и сети не меняются — их форма задана task-001/ADR-005.

- **Touch ONLY (создать/наполнить):**
  - `apps/trendPulse/ops/terraform/` — `main.tf` (провайдеры), `versions.tf` (`required_providers` + версии), `backend.tf` (remote state + lock), `variables.tf` (вход; чувствительные `sensitive = true`), `outputs.tf`, ресурсы: `dns.tf` (записи на edge), `vps.tf` (инстанс провайдера), `firewall.tf` (только 443 + 80-redirect, прочее закрыто; SSH allowlist), опц. `object_storage.tf`; `terraform.tfvars.example` (без секретов); `.gitignore` (`*.tfvars` кроме `*.example`, `.terraform/`, `*.tfstate*`).
  - `apps/trendPulse/ops/ansible/` — `ansible.cfg`, `inventory/` (`hosts.ini` / `inventory.yml`), `site.yml` (главный playbook), `playbooks/` (`provision.yml` — docker/compose/системные пакеты; `deploy.yml` — выкладка стека; `unpack-env.yml` — рендер `deploy.env` + расшифровка `sensitive.env`), `group_vars/all.yml` (несекретные дефолты), `group_vars/prod.yml` (prod-настройки), `vault/sensitive.vault.yml` (ansible-vault encrypted — секреты), `roles/` (по необходимости: `docker`, `deploy`, `env`), `templates/deploy.env.j2` (шаблон несекретного env), `requirements.yml` (galaxy-коллекции, напр. `community.docker`), `.gitignore` (`*.vault-pass`, расшифрованные дампы).
  - `apps/trendPulse/Makefile` — наполнить таргет `ansible-unpack` (объявлен в task-001): `ansible-playbook playbooks/unpack-env.yml` → рендер `development/env/deploy.env` из `group_vars/*` + расшифровка `development/env/sensitive.env` из vault; опц. helper-таргеты `tf-validate`, `ansible-lint`, `ansible-check` (обёртки для AC/CI).
  - `apps/trendPulse/.gitignore` — убедиться, что `development/env/sensitive.env` (и `development/env/deploy.env`, т.к. материализуется из Ansible) гитигнорятся; vault-pass-файлы и `*.tfstate*` тоже.
  - Документация потока в `ops/README.md` (схема `group_vars`/`vault` → `ansible-unpack` → `development/env/` → compose; команды через `make`).
- **Do NOT touch:** `_bmad/**`, `.claude/**`, `docs/**` (кроме обновления `tasks-index.md` на ship), `backend/**`, `landing/**`, `frontend/**`, `development/compose/**`, `development/docker-compose.yml`, `development/provisioning/**`. Никакой бизнес-логики; форму env-переменных задаёт ADR-005/task-001, здесь — только их источник и доставка.
- **Blast radius:** потребители — `make up`/`make ansible-unpack` (нужны непустые `development/env/{deploy.env,sensitive.env}`), prod-деплой (Ansible выкладывает стек и env на VPS), сетевой контур (firewall в TF обязан совпадать с network-design). Ломается всё, если `ansible-unpack` отдаёт пустые/неполные env. Задаёт контракт: имена переменных в `group_vars`/vault = ключи, которые ждут compose-сервисы.

## Acceptance Criteria
- [ ] **AC1 — провал ДО реализации (RED-якорь).** Given пустой/скелетный `ops/`, When `make ansible-unpack` (и/или `make tf-validate`), Then команда **падает** — `development/env/{deploy.env,sensitive.env}` не появляются (или `terraform validate` ругается на отсутствие конфигурации). Это фиксируемый старт: до наполнения `ops/` проверка обязана быть красной.
- [ ] **AC2 — `terraform validate` чист.** Given наполненный `ops/terraform`, When `terraform -chdir=ops/terraform init -backend=false && terraform -chdir=ops/terraform validate`, Then exit 0, конфигурация валидна, без неразрешённых ссылок.
- [ ] **AC3 — `ansible-lint` зелёный.** Given playbooks/roles, When `ansible-lint` по `ops/ansible`, Then нет ошибок (warnings допустимы и зафиксированы), синтаксис и best-practices проходят.
- [ ] **AC4 — dry-run проходит.** Given inventory + vault-pass, When `ansible-playbook ops/ansible/site.yml --check` (и `--syntax-check`), Then exit 0, без неопределённых переменных и сломанных задач.
- [ ] **AC5 — `make ansible-unpack` материализует env.** Given `group_vars/*` + расшифровываемый vault, When `make ansible-unpack`, Then создаются **непустые** `development/env/deploy.env` (несекретные дефолты из `group_vars`) и `development/env/sensitive.env` (секреты из vault), оба пригодны для `env_file` compose.
- [ ] **AC6 — нет plaintext-секретов в git.** Given репозиторий, When проверка (`git grep`/scan по индексу + статус игнора), Then `sensitive.env` не закоммичен и гитигнорится; `vault/*.vault.yml` хранится **только** в зашифрованном виде; в `*.tf`/`*.tfvars`/`group_vars` нет открытых секретов.
- [ ] **AC7 — firewall = network-design.** Given `ops/terraform/firewall.tf`, When ревью правил, Then наружу открыты только 443 и 80 (redirect→443), SSH ограничен allowlist'ом, прочий ingress закрыт (зеркало [network-design](../architecture/network-design.md)).
- [ ] **AC8 — make как точка входа.** Given чистый checkout, When `make help`, Then `ansible-unpack` (и helper-таргеты для AC2–AC4) перечислены и работают без ручных `terraform`/`ansible-playbook` вызовов.

## Plan
0. Locate: подтвердить скелет `ops/` от task-001 и объявление таргета `ansible-unpack` в root `Makefile`; зафиксировать `baseline_commit`.
1. **RED (AC1):** прогнать `make ansible-unpack` / `make tf-validate` на пустом `ops/` — убедиться, что падает и env-файлы не появляются. Зафиксировать как стартовое состояние.
2. `ops/terraform/`: `versions.tf` (`required_providers` + version pins), `main.tf` (провайдеры), `backend.tf` (remote state + lock; backend-креды через env/`-backend-config`), `variables.tf` (вход; чувствительные `sensitive = true`), `outputs.tf`. Затем `terraform fmt` + `terraform init -backend=false` + `terraform validate` → зелёный (AC2).
3. `ops/terraform/` ресурсы: `dns.tf`, `vps.tf`, `firewall.tf` (только 443 + 80-redirect, SSH allowlist — зеркало network-design, AC7), опц. `object_storage.tf`; `terraform.tfvars.example` (без секретов).
4. `ops/ansible/`: `ansible.cfg`, `inventory/`, `requirements.yml`. `group_vars/all.yml` (несекретные дефолты: имена БД, порты, имена сетей, URL-шаблоны, фичефлаги), `group_vars/prod.yml` (prod-override). `vault/sensitive.vault.yml` через `ansible-vault create/encrypt` (секреты: пароль БД, JWT secret, NOWPayments API key/IPN secret, OAuth client secret, Telegram pool creds).
5. `templates/deploy.env.j2` + playbook `playbooks/unpack-env.yml`: рендер `deploy.env` из `group_vars/*` и расшифровка `sensitive.env` из vault → запись в `development/env/`. `site.yml` + `playbooks/provision.yml` (docker/compose, системные пакеты) + `playbooks/deploy.yml` (выкладка стека + env на VPS).
6. Наполнить root `Makefile` таргет `ansible-unpack` (ansible-playbook unpack-env.yml с `--vault-password-file`); добавить helper-таргеты `tf-validate`, `ansible-lint`, `ansible-check`.
7. Прогнать `ansible-lint` (AC3), `ansible-playbook --syntax-check`/`--check` (AC4); зафиксировать `.gitignore` для `sensitive.env`/`deploy.env`/`*.tfstate*`/vault-pass (AC6).
8. **GREEN (AC5):** `make ansible-unpack` → проверить непустые `development/env/{deploy.env,sensitive.env}`; затем `make up` на этих env. Прогнать `git grep`-скан секретов (AC6).
9. `ops/README.md` — документировать поток `group_vars`/`vault` → `make ansible-unpack` → `development/env/` → compose; команды только через `make`; заметка о ротации (AC + security 5.5).

## Invariants
- **Ansible — единственный источник истины по env-переменным** (локально и на prod); `deploy.env`/`sensitive.env` всегда материализуются из `group_vars`/vault через `make ansible-unpack`, вручную не редактируются.
- **`make` (root `apps/trendPulse/Makefile`) — единственная точка входа.** Raw `terraform`/`ansible-playbook`/`docker compose` — только внутри таргетов, не в инструкциях/доках/CI.
- **Ни одного plaintext-секрета в git.** Секреты живут в ansible-vault (encrypted); `sensitive.env` гитигнор; в `*.tf`/`*.tfvars`/`group_vars` секретов нет; backend/vault-пароли — из env/файлов вне репо.
- **Terraform = внешние сервисы, Ansible = настройка хоста.** Граница «provision (TF) → configure (Ansible)» не размывается.
- **Firewall зеркалит network-design:** наружу только 443 (+80 redirect), least-privilege на ingress и SSH; БД/Redis портов наружу не открывают (это compose/сети, не TF — TF их и не публикует).
- **Terraform state — remote с lock**, никогда не local-`.tfstate` в git; `*.tfstate*` гитигнор.
- **Чувствительные TF-переменные помечены `sensitive = true`**; значения — через `TF_VAR_*`/`-var-file` вне git.

## Edge cases
- Vault-пароль отсутствует/неверный → `ansible-unpack` падает с понятной ошибкой (не молча отдаёт пустой `sensitive.env`); требовать `--vault-password-file`/`ANSIBLE_VAULT_PASSWORD_FILE`.
- Рассинхрон ключей: переменная в `group_vars`/vault отсутствует, а compose её ждёт → `--check`/рендер должен валить на undefined; держать `deploy.env.j2` строгим (`StrictUndefined`).
- `terraform validate` без `init` падает на провайдерах → использовать `init -backend=false` для валидации без доступа к remote backend.
- Дрейф firewall vs network-design: правило шире, чем 443/80 → ревью AC7; любой лишний открытый порт = провал.
- `deploy.env` материализуется из Ansible (источник истины) → НЕ коммитить его, даже будучи «несекретным» (иначе два источника истины); в git только шаблон/`group_vars`.
- Ротация секрета: меняется в vault (`ansible-vault edit`) → `make ansible-unpack` перегенерит `sensitive.env`; на prod — повторный `deploy`. Старое значение считать скомпрометированным.
- Remote backend недоступен/конфликт lock → `validate` идёт с `-backend=false`; реальные операции (`plan`/`apply`) — отдельная ручная процедура вне этой задачи.
- Object storage не нужен на старте → не вводить ресурс ради ресурса; контракт переменных заложить, ресурс — при потребности (бэкапы/артефакты).

## Test plan
- **static (AC2):** `terraform fmt -check` + `terraform -chdir=ops/terraform init -backend=false && terraform validate` → exit 0 (пишется/проверяется ПЕРВЫМ как зелёный гейт TF).
- **lint (AC3):** `ansible-lint` по `ops/ansible` → нет ошибок.
- **dry-run (AC4):** `ansible-playbook ops/ansible/site.yml --syntax-check` + `--check` → exit 0, нет undefined-переменных.
- **materialization (AC5, behavioral):** `make ansible-unpack` → ассертить непустые `development/env/deploy.env` и `development/env/sensitive.env` (ключи присутствуют, значения непустые); затем `make up` стартует на этих env.
- **secret hygiene (AC6):** `git grep`/scan по индексу — нет plaintext-секретов; `git check-ignore development/env/sensitive.env` подтверждает игнор; `head` vault-файла показывает `$ANSIBLE_VAULT;…` (encrypted).
- **firewall (AC7):** ревью `firewall.tf` — только 443 + 80-redirect открыты, SSH allowlist, прочее закрыто.

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: done
baseline_commit: "40c932904e13d93d4ccd818f5b247e8f1abf5c20"
branch: "gsd/phase-012-ops-iac"
lock: "loop-012"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing check → minimal IaC)
- [x] 4 verify (G2 — validate/lint/check + materialized env + real behavior)
- [x] 5 review (auto — 2 HIGH deploy.yml source/version.env delivery fixed)
- [x] 5.5 security (REQUIRED — PASS, 0 blocking; vault encrypted, firewall least-priv)
- [x] 6 ship (PR #12, squash-merged)
- [x] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial — план составлен по ADR-005 §4/§5 и network-design; реализует скелет `ops/` из task-001. Зависит от task-001 — root `Makefile`, `development/env/`, объявленный таргет `ansible-unpack`.)


### Step 3 do · 4 verify · 5 review · 5.5 security · loop-012
- **do (ops/ only):** ops/terraform (digitalocean provider: versions/main/backend(remote, init-time creds)/variables(sensitive=true)/outputs/vps/firewall/dns/object_storage + tfvars.example + .gitignore); ops/ansible (ansible.cfg, inventory, site.yml, playbooks provision/deploy/unpack-env, group_vars all+prod, roles/env, **ansible-vault ENCRYPTED** vault, requirements.yml, README). Root Makefile: ansible-unpack → ansible-playbook unpack-env.yml (--vault-password-file .vault-pass) + tf-validate/ansible-lint/ansible-check helpers in `make help`. Stub `ansible-unpack.sh` + plaintext vault.yml removed. `deploy.env` git-untracked (теперь Ansible-материализуется).
- **verify (G2):** AC2 `terraform validate` Success; AC3 ansible-lint production-profile clean; AC4 `--syntax-check`/`--check` pass; AC5 `make ansible-unpack` → deploy.env (12) + sensitive.env (10) непустые, **env-контракт = superset** прежних ключей (+TELEGRAM_POOL_SESSIONS, 0 потеряно); AC6 vault `$ANSIBLE_VAULT;1.1;AES256`, `.vault-pass`/sensitive.env/deploy.env gitignored, нет plaintext-секретов; AC7 firewall 443/80-redirect/SSH-allowlist (зеркало network-design); AC8 make help. Backend ci-fast не затронут (211).
- **review (opus) → 2 HIGH → fixed (debug cycle 1):** `deploy.yml` не доставлял app-source/version.env на VPS → prod compose-up некогерентен. **FIX:** `pre_tasks` git-clone `{{ app_repo_url }}@{{ app_version }}` → app_dir; `docker_compose_v2 env_files=[version.env]` (image-tag интерполяция). ansible-lint/syntax по-прежнему чисты. LOW (prod.yml trendpulse_debug) — оставлен как explicit prod re-assert.
- **security (opus) PASS, 0 blocking:** vault только зашифрованным blob'ом; нет plaintext в .tf/.tfvars/group_vars/Makefile; `.vault-pass` (только путь в ansible.cfg) gitignored+untracked; TF secrets sensitive=true, backend creds init-time, tfstate/tfvars gitignored, outputs без секретов; firewall least-priv (SSH default 127.0.0.1/32, не 0.0.0.0/0); sensitive.env 0600; **prod.yml `auth_cookie_secure=true` — закрыл prod-долг task-009**; Spaces ACL private; SSH key-auth. Нечего ротировать. INFO: egress 0.0.0.0/0 (приемлемо для пакетов/ACME).
