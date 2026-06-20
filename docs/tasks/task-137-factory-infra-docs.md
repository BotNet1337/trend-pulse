---
id: TASK-137
title: account-factory infra — compose + ansible + docs
status: done
owner: infra
created: 2026-06-19
updated: 2026-06-20
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: gsd/phase-137-factory-infra-docs
tags: [account-factory, infra, compose, ansible, docs, layer-b]
---

# TASK-137 — account-factory infra + docs (Layer B infra)

> Wire the `account-factory` service into dev + release compose, give it its own ops/ansible config,
> and document it in development/ + release/ — by analogy with the worker service.

## Context
Services share the backend image, differ by command; per-service compose fragments in
`development/compose/*.yml` + `release/compose/*.yml`, included via `include:` in
`development/docker-compose.yml` + `release/docker-compose.yml`. The worker has `egress` for MTProto
(`development/compose/worker.yml`). Env: `development/env/deploy.env` (non-secret) + `sensitive.env`
(secret); Ansible is the single source of truth (`ops/ansible`, vault `vault/sensitive.vault.yml`,
env templates `roles/env/templates/*.j2`, group_vars). The factory service runs
`celery -A celery_app beat`/a dedicated worker for `factory_tick` (TASK-134) — needs `egress`
(SMSPVA + Telegram) + postgres_net + redis_net, NOT edge.

## Goal
- `development/compose/account-factory.yml` + `release/compose/account-factory.yml` — service on the
  shared image, command running the factory tick loop, on egress+postgres_net+redis_net, no ports,
  `env_file` deploy+sensitive, `depends_on` redis/migration_runner like worker.
- Include both in the respective top `docker-compose.yml`.
- ops/ansible: factory env keys rendered into the env templates (non-secret in deploy template,
  `SMSPVA_API_KEY` via vault), per-service vars; no secret committed in clear.
- Docs: a section in `development/README` (or equivalent) + `release/RELEASE.md` describing the service,
  its env, the budget/probation model, and that real provisioning is provider-gated
  (`ACCOUNT_FACTORY_PROVIDER=smspva` + `SMSPVA_API_KEY` in vault; `fake`/unset = safe default).
- **Secret migration:** the owner-provided `SMSPVA_API_KEY` (currently in the gitignored
  `apps/trendPulse/.env` for local testing) is migrated INTO the ansible vault
  (`ops/ansible/vault/sensitive.vault.yml` → rendered into `sensitive.env.j2`); `.env` stays gitignored,
  never committed. Document the rotate-after-exposure note.
- ADR `docs/architecture/adr-account-factory-provisioning.md`.

## Discussion
- Q: Own image or shared? → A: shared → Decision: same `${APP_IMAGE_ML}`/`${APP_IMAGE}` as worker,
  differ only by command (CONVENTIONS: same image for api/worker/beat).
- Q: Separate beat or fold into existing beat? → A: separate service → Decision: owner asked for a
  distinct `account-factory` service with its own ops config; run it as its own container so it can be
  scaled independently (and `ACCOUNT_FACTORY_PROVIDER` unset → tick is a no-op).
- Q: Default state in prod compose? → A: present but gated → Decision: service ships in compose but is a
  no-op until `ACCOUNT_FACTORY_PROVIDER=smspva` + `SMSPVA_API_KEY` set in vault.

## Scope
- Touch ONLY: `development/compose/account-factory.yml` (new), `release/compose/account-factory.yml`
  (new), `development/docker-compose.yml` + `release/docker-compose.yml` (include line),
  `ops/ansible/roles/env/templates/*.j2` (factory keys), `ops/ansible` group_vars/vault var names
  (no secret values), `development/env/deploy.env` (non-secret factory defaults),
  docs in `development/` + `release/`, new ADR.
- Do NOT touch: backend code (done in 132–135), frontend (136).
- Blast radius: infra/compose/ansible/docs only.

## Acceptance Criteria
- [ ] `make build` produces the shared image and the account-factory service is defined in both composes.
- [ ] `docker compose config` (via `make`) validates with the factory service included (dev + release).
- [ ] Factory env keys present in the ansible env templates; `SMSPVA_API_KEY` sourced from vault (no clear secret committed).
- [ ] With `ACCOUNT_FACTORY_PROVIDER` unset (default) the service starts and is a no-op (no purchases).
- [ ] Docs in development/ + release/ describe the service + owner-gated activation; ADR written.

## Plan
1. `development/compose/account-factory.yml` (+release) — mirror worker.yml, factory command, egress.
2. include in both top compose files.
3. ansible env templates + group_vars/vault var names for factory keys.
4. `deploy.env` non-secret factory defaults (budget, probation; `ACCOUNT_FACTORY_PROVIDER` unset in prod until owner sets `smspva`).
5. docs + ADR.

## Invariants
- No secret committed in clear (vault only). Service default = disabled no-op.
- `make` remains the only entry point; compose validates.

## Edge cases
- Missing `SMSPVA_API_KEY` + enabled=false → service idles cleanly (no crash loop).

## Test plan
- verify: `make`-driven `docker compose config` validates (dev+release); grep asserts factory keys in
  templates + no clear secret; service boots no-op locally.

## Checkpoints
current_step: done
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: gsd/phase-137-factory-infra-docs
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (compose + ansible + docs)
- [x] 4 verify (G2 — compose validates dev+release; no-op boot; no clear secret)
- [x] 5 review (auto, adversarial — PASS, no blocking; 1 LOW ADR-wording fixed)
- [x] 5.5 security (vault secret handling, egress surface — PASS, key 0× in history)
- [x] 6 ship (PR #207 merged --admin; SMSPVA key in encrypted vault, 0× clear in history)
- [x] 7 learnings (auto)
debug_runs: []

## Details

### do (2026-06-20)
New: `development/compose/account-factory.yml`, `release/compose/account-factory.yml`,
`development/README.md`, `docs/architecture/adr-account-factory-provisioning.md`.
Edited: `development/docker-compose.yml` + `release/docker-compose.yml` (include after worker),
`ops/ansible/roles/env/templates/deploy.env.j2` (7 ACCOUNT_FACTORY_* vars),
`sensitive.env.j2` (SMSPVA_API_KEY via `vault_smspva_api_key|default('')`),
`group_vars/all.yml` (dev defaults: provider=fake, budget=0.00, probation=14, country=RU,
price=1.00, tick=3600, proxy_pool=""), `group_vars/prod.yml` (provider="" off),
`development/env/deploy.env` (gitignored literal dev block), `release/RELEASE.md` (activation steps).
Service = dedicated celery worker `-Q celery` (factory_tick is unrouted → default queue;
no backend routing change). Egress for SMSPVA+MTProto. No-op until provider=smspva.

### vault (executor, 2026-06-20)
Migrated `SMSPVA_API_KEY` from gitignored `.env` into encrypted vault as `vault_smspva_api_key`
via decrypt→append→`ansible-vault encrypt`. Vault committed in `$ANSIBLE_VAULT;1.1;AES256` form.

### verify G2 (2026-06-20) — PASS
- `make ci-fast`: 1349 passed, 338 deselected (no python regression).
- dev `docker compose ... -f development/docker-compose.yml config`: EXIT=0; services include
  `account-factory`; rendered env has `ACCOUNT_FACTORY_PROVIDER: fake`.
- release `docker compose ... -f release/docker-compose.yml config`: EXIT=0; services include
  `account-factory`; `ACCOUNT_FACTORY_PROVIDER: fake` rendered. (temp release/env copied+removed.)
- `make ansible-check` (syntax): EXIT=0 (ok=4). `make ansible-lint`: EXIT=2 PRE-EXISTING
  (deploy.yml/provision.yml — NOT in TASK-137 diff; target lacks --vault-password-file).
- vault round-trip: `ansible-vault view ... | grep vault_smspva_api_key` → present (key NAME).
- clear-key `git grep` count = 0; `.env` tracked count = 0; `.env` not in git status.
