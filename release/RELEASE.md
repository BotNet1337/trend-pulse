# Release notes — manual steps journal

Incremental manual steps required per version, oldest → newest. Start from your
currently-deployed version and apply each subsequent section in order. Most
deploys need **no** manual steps (the playbook + swarm jobs are idempotent); this
file exists for the exceptions (one-time data migrations, new required secrets,
breaking config changes).

Versioning model: an annotated semver tag `vX.Y.Z` on `main`. `app_version=<tag>`
flows through Ansible → built image tags (`trendpulse-*:vX.Y.Z`) → `RELEASE` env
(Sentry) → `docker stack ps` (the live version on the host).

---

## Unreleased — proxy auto-provisioning (Layer B-proxy, TASK-142)

Proxy-провайдер для account-factory включён в стек compose (dev + release), но
**является no-op по умолчанию** — `ACCOUNT_FACTORY_PROXY_PROVIDER` пустой в prod.
Никаких реальных выделений proxy не происходит без трёх шагов активации:

1. В `ops/ansible/inventory/group_vars/prod.yml` выставить:
   ```yaml
   account_factory_proxy_provider: "mobileproxy"
   account_factory_proxy_price_usd: "33.00"   # guard: стоимость одного мобильного IP
   account_factory_health_probe_channel: "@telegram"
   ```
2. Добавить Bearer API-токен Mobileproxy.space в vault:
   ```bash
   ansible-vault edit ops/ansible/vault/sensitive.vault.yml
   # добавить: vault_mobileproxy_api_token: "<токен>"
   ```
3. Задеплоить: `make deploy`.

> **Rotate-after-exposure**: если `vault_mobileproxy_api_token` скомпрометирован —
> немедленно отозвать токен в личном кабинете Mobileproxy.space, создать новый,
> обновить vault, передеплоить.

Взаимодействие с бюджетом: `ACCOUNT_FACTORY_PROXY_PRICE_USD` — guard на стоимость
одного прокси-слота. `"0.00"` отклоняет каждое выделение даже при включённом
провайдере (двойная защита от случайных расходов).

Misconfig fail-fast: если провайдер = `mobileproxy`, но токен не задан → `FactoryError`
при первом тике. Это ожидаемый сигнал неправильной конфигурации, не краш.

До активации сервис стартует и работает в статическом-pool режиме (TASK-141 заменяет
stub на реальный health-probe через session+proxy только при включённом провайдере).

---

## Unreleased — account-factory (Layer B, TASK-137)

Сервис `account-factory` включён в стек (development + release compose), но
**является no-op по умолчанию** — никаких реальных покупок не происходит пока не
выполнены все три шага активации:

1. В `ops/ansible/inventory/group_vars/prod.yml` выставить:
   ```yaml
   account_factory_provider: "smspva"
   account_factory_budget_usd: "5.00"   # или нужный лимит
   ```
2. Добавить SMSPVA API-ключ в vault:
   ```bash
   ansible-vault edit ops/ansible/vault/sensitive.vault.yml
   # добавить: vault_smspva_api_key: "<ключ>"
   ```
3. Задеплоить: `make deploy` (или через CD-пайплайн).

> **Rotate-after-exposure**: если `vault_smspva_api_key` был скомпрометирован —
> немедленно сгенерировать новый ключ в личном кабинете SMSPVA, обновить vault,
> передеплоить. Старый ключ деактивировать.

До активации сервис стартует, потребляет очередь `celery`, но `factory_tick`
завершается мгновенно (пустой провайдер = no-op). Бюджет `"0.00"` в dev — дополнительная
защита: даже при случайно выставленном провайдере покупок не будет.

---

## v0.1.0 — initial production launch

First deploy of the `release/` bundle on Docker Swarm. One-time owner steps
(see the task doc / root README for the full owner checklist):

1. Rent a VPS (Ubuntu 22.04/24.04, ≥4 GB RAM) and put its IP in
   `ops/ansible/inventory/prod.yml` (copy from `inventory/prod.example.yml`).
2. Point the domain A-record at the VPS IP (TLS issuance needs DNS to resolve).
3. Fill the vault: SMTP (Resend) is already set; add `FIELD_ENCRYPTION_KEY`
   (Fernet, 32-byte urlsafe-base64) and any optional bot tokens.
4. First deploy from the laptop: `make deploy` (repo root).
5. One-time for tag-based CD: configure the GitHub `production` environment
   secrets (`SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`, `ANSIBLE_VAULT_PASSWORD`,
   `PROD_HOST`, `PROD_DOMAIN`, `LETSENCRYPT_EMAIL`).

Thereafter every release is `git tag vX.Y.Z && git push origin vX.Y.Z`.

> Rollback to a previous version is a `workflow_dispatch` of `deploy-tag.yml`
> with the old tag (or `make deploy` with `-e app_version=<old-tag>`). Alembic
> migrations are **not** auto-downgraded — `alembic downgrade` is a manual,
> reviewed operation.
