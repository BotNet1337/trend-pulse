# apps/trendPulse/Makefile — THE single entry point (ADR-005 §1, CONVENTIONS).
# Use `make up`, never `make -C development ...` or raw `docker compose`/`uv`.
#
# Docker targets wrap compose with --env-file version.env (image/build-arg pins)
# + the top per-service compose file. Dev/CI targets wrap `uv run` in backend/.

# deploy.env + sensitive.env are needed for INTERPOLATION (e.g. the required
# ${FRONTEND_COOKIE_SECRET:?} in frontend.yml) — compose does not read service
# `env_file:` entries at parse time. They exist after `make ansible-unpack`.
COMPOSE         := docker compose \
  --env-file development/version.env \
  --env-file development/env/deploy.env \
  --env-file development/env/sensitive.env \
  -f development/docker-compose.yml
# Backup targets invoke pg-backup.yml directly — standalone, no root include.
# This avoids the FRONTEND_COOKIE_SECRET interpolation failure when the full
# env is not loaded.  The env files exist after `make ansible-unpack`.
COMPOSE_BACKUP  := docker compose \
  --env-file development/version.env \
  --env-file development/env/deploy.env \
  --env-file development/env/sensitive.env \
  -f development/compose/pg-backup.yml \
  --profile backup
UV      := uv run --directory backend
INFRA   := postgres redis pg_vector_provisioner migration_runner
# OpenAPI contract (TASK-019): committed dump + generated types paths.
OPENAPI_DUMP := frontend/src/shared/api/openapi.json
GEN_TYPES    := frontend/src/shared/api/gen.types.ts
# Dummy auth secrets satisfy the fail-fast Settings fields; no real secrets
# needed to build the schema offline — SWAGGER_ENABLE not required either.
GEN_DUMP_ENV := JWT_SECRET=dump OAUTH_STATE_SECRET=dump GOOGLE_CLIENT_ID=dump GOOGLE_CLIENT_SECRET=dump
# IaC dirs (ADR-005 §5). Ansible runs with cwd = ops/ansible so ansible.cfg +
# .vault-pass (gitignored dev vault password) resolve relative to it.
ANSIBLE_DIR := ops/ansible
TF_DIR      := ops/terraform

.PHONY: help up dev-up dev-infra-up down build logs logs-once ps restart sh migrate \
        ansible-unpack tf-validate ansible-lint ansible-check \
        lint fmt typecheck test test-cov test-integration ci ci-fast \
        gen-openapi gen-types openapi-drift-check \
        backup backup-restore-check \
        showcase-init case-mainstream referral-paid superuser-grant

# Default target: list everything.
help:
	@echo "TrendPulse — make targets (run from apps/trendPulse):"
	@echo ""
	@echo "  Stack:"
	@echo "    up               bring up the full stack (infra -> provisioning -> app -> nginx)"
	@echo "    dev-up           bring up the full stack in the background (alias of up)"
	@echo "    dev-infra-up     bring up ONLY infra + provisioning (postgres, redis, provisioners)"
	@echo "    down             stop and remove everything"
	@echo "    build            build the app image(s)"
	@echo "    restart          restart all services"
	@echo "  Ops:"
	@echo "    logs             follow logs for all services"
	@echo "    ps               list service status"
	@echo "    sh               open a shell in the api container"
	@echo "    migrate          run migration_runner (alembic upgrade head)"
	@echo "    ansible-unpack   render development/env/{deploy,sensitive}.env from ops/ansible"
	@echo "    backup           pg_dump → Hetzner Object Storage (one-shot, requires S3_* env)"
	@echo "    backup-restore-check  download latest dump → disposable PG → smoke-check (PASS/FAIL)"
	@echo "  IaC (ops/ — Terraform + Ansible, ADR-005 §5):"
	@echo "    tf-validate      terraform init -backend=false + validate (ops/terraform/environments/{org,prod})"
	@echo "    ansible-lint     ansible-lint over ops/ansible"
	@echo "    ansible-check    ansible-playbook --syntax-check + --check (dry-run)"
	@echo "  Dev / CI (uv run in backend/):"
	@echo "    fmt              ruff format"
	@echo "    lint             ruff check"
	@echo "    typecheck        mypy (strict)"
	@echo "    test             pytest -m 'not integration'"
	@echo "    test-integration pytest -m integration"
	@echo "    ci               fmt-check + lint + typecheck + FULL test + openapi-drift-check"
	@echo "    ci-fast          fmt-check + lint + typecheck + test (not integration)"
	@echo "    test-cov         unit tests with coverage gate (≥80%, from [tool.coverage.report])"
	@echo "  OpenAPI contract (TASK-019 — offline, no make up required):"
	@echo "    gen-openapi      dump app.openapi() → $(OPENAPI_DUMP) (no server)"
	@echo "    gen-types        regen $(GEN_TYPES) from the committed dump"
	@echo "    openapi-drift-check  gen-openapi + gen-types + git diff --exit-code (fail on drift)"
	@echo "  Showcase cases (TASK-045):"
	@echo "    case-mainstream  ID=<id> AT=<iso8601>  set mainstream_at on a showcase_cases row"
	@echo "  Referral program (TASK-046):"
	@echo "    referral-paid    ID=<reward_id>  mark a referral_rewards row as paid"
	@echo "  Superuser ops (TASK-051):"
	@echo "    superuser-grant  EMAIL=<email>   idempotently grant superuser flag to a user"

# --- Stack ---
up:
	$(COMPOSE) up -d

dev-up: up

dev-infra-up:
	$(COMPOSE) up -d $(INFRA)

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

restart:
	$(COMPOSE) restart

# --- Ops ---
logs:
	$(COMPOSE) logs -f

# Non-following log dump (bounded) — for CI/diagnostics where `logs -f` would hang.
logs-once:
	$(COMPOSE) logs --no-color --tail=500

ps:
	$(COMPOSE) ps

sh:
	$(COMPOSE) exec api sh

migrate:
	$(COMPOSE) up --no-deps migration_runner

ansible-unpack:
	cd $(ANSIBLE_DIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook playbooks/unpack-env.yml --vault-password-file .vault-pass

# --- Backup (TASK-034) ---
# pg_dump -Fc → Hetzner Object Storage. Two one-shot containers:
#   pg_backup (pgvector image, postgres_net) → dump to shared volume
#   backup_uploader (aws-cli image) → upload to s3://$S3_BUCKET/postgres/<ts>.dump
# Requires S3_* env from sensitive.env (populated by `make ansible-unpack`).
# Uses pg-backup.yml directly (standalone) — avoids FRONTEND_COOKIE_SECRET failure.
#
# F1: run ONLY the terminal service — depends_on chains the first stage automatically.
#   Running both services explicitly caused pg_dump (and S3 fetch) to execute twice.
backup:
	$(COMPOSE_BACKUP) run --rm backup_uploader

# Download latest dump from S3 → restore into a throwaway internal PG → smoke checks.
# Two one-shot containers: restore_fetch (aws-cli) + restore_check (pgvector, internal PG).
# NO docker socket. Reports PASS/FAIL; always cleans up via trap.
# Requires S3_* env from sensitive.env (populated by `make ansible-unpack`).
#
# F1: run ONLY the terminal service — depends_on chains restore_fetch automatically.
# F5: `down --volumes` removes project-local named volumes (pgdump_tmp, restore_tmp)
#   after a successful check so the prod dump copy does not linger on disk.
#   This targets ONLY the pg-backup.yml project volumes — main stack volumes are
#   in a different compose project and are unaffected.
backup-restore-check:
	$(COMPOSE_BACKUP) run --rm restore_check
	$(COMPOSE_BACKUP) down --volumes

# --- IaC (ops/ — Terraform + Ansible) ---
# validate without touching the remote backend (AC2; -backend=false). init
# fetches provider schemas; needs network the first time.
tf-validate:
	terraform -chdir=$(TF_DIR)/environments/org init -backend=false
	terraform -chdir=$(TF_DIR)/environments/org validate
	terraform -chdir=$(TF_DIR)/environments/prod init -backend=false
	terraform -chdir=$(TF_DIR)/environments/prod validate

ansible-lint:
	ansible-lint $(ANSIBLE_DIR)

# Dry-run: syntax-check the whole site, plus a localhost --check of unpack-env
# (the only play that runs without a real host).
ansible-check:
	cd $(ANSIBLE_DIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook site.yml --syntax-check --vault-password-file .vault-pass
	cd $(ANSIBLE_DIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook playbooks/unpack-env.yml --check --vault-password-file .vault-pass

# --- Dev / CI ---
fmt:
	$(UV) ruff format .

lint:
	$(UV) ruff check .

typecheck:
	$(UV) mypy

test:
	$(UV) pytest -m 'not integration'

test-integration:
	$(UV) pytest -m integration

test-cov:
	$(UV) pytest -m 'not integration' --cov

ci:
	$(UV) ruff format --check .
	$(UV) ruff check .
	$(UV) mypy
	$(UV) mypy scripts/dump_openapi.py
	$(UV) pytest
	$(MAKE) openapi-drift-check

ci-fast:
	$(UV) ruff format --check .
	$(UV) ruff check .
	$(UV) mypy
	$(UV) mypy scripts/dump_openapi.py
	$(UV) pytest -m 'not integration'

# --- OpenAPI contract (TASK-019): offline dump of app.openapi() to a committed
# file (no server), then regen frontend types from it.  Drift-check keeps the
# committed contract in sync with the routes.  Dummy auth secrets satisfy the
# fail-fast Settings fields — no real secrets needed to build the schema offline.
gen-openapi:
	$(GEN_DUMP_ENV) $(UV) python scripts/dump_openapi.py

gen-types:
	cd frontend && npm run gen:api

# Uses `git status --porcelain` (not `git diff --exit-code`) so the check also
# catches an UNTRACKED dump (a forgotten `git add` of openapi.json) — `git diff`
# is blind to untracked files and would silently pass.
openapi-drift-check: gen-openapi gen-types
	@if [ -n "$$(git status --porcelain -- $(OPENAPI_DUMP) $(GEN_TYPES))" ]; then \
		echo "OpenAPI drift detected — run 'make gen-openapi gen-types' and commit the result:"; \
		git status --porcelain -- $(OPENAPI_DUMP) $(GEN_TYPES); \
		exit 1; \
	fi

# --- Showcase tenant bootstrap (TASK-039) ---
# Creates the system showcase user + subscribes to all catalog packs.
# Idempotent: safe to re-run. Requires the stack to be up (postgres accessible).
# Run once after `make up` on a fresh deploy or when catalog changes.
showcase-init:
	$(COMPOSE) exec api uv run python -m api.trending

# --- Proof-of-speed cases — operator mainstream mark (TASK-045) ---
# Set mainstream_at on a showcase_cases row.
# Usage: make case-mainstream ID=<id> AT="2026-06-10T15:00:00Z"
# Validates: mainstream_at must be strictly after first_seen (refuses otherwise).
# Requires: stack up (postgres accessible via api container).
case-mainstream:
	$(COMPOSE) exec api uv run python scripts/case_mainstream.py --id '$(ID)' --at '$(AT)'

# --- Referral program — operator paid mark (TASK-046) ---
# Mark a referral_rewards row as paid (status=paid, paid_at=now).
# Usage: make referral-paid ID=<reward_id>
# Validates: row exists and is currently 'pending'.
# Requires: stack up (postgres accessible via api container).
referral-paid:
	$(COMPOSE) exec api uv run python scripts/referral_paid.py --id '$(ID)'

# --- Superuser grant (TASK-051) ---
# Idempotently set is_superuser=True for a user by email.
# Usage: make superuser-grant EMAIL=<email>
# Validates: user with given email must exist (exits non-zero with human error otherwise).
# Requires: stack up (postgres accessible via api container).
superuser-grant:
	$(COMPOSE) exec api uv run python scripts/superuser_grant.py --email '$(EMAIL)'
