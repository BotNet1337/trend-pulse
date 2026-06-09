# apps/trendPulse/Makefile — THE single entry point (ADR-005 §1, CONVENTIONS).
# Use `make up`, never `make -C development ...` or raw `docker compose`/`uv`.
#
# Docker targets wrap compose with --env-file version.env (image/build-arg pins)
# + the top per-service compose file. Dev/CI targets wrap `uv run` in backend/.

COMPOSE := docker compose --env-file development/version.env -f development/docker-compose.yml
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

.PHONY: help up dev-up dev-infra-up down build logs ps restart sh migrate \
        ansible-unpack tf-validate ansible-lint ansible-check \
        lint fmt typecheck test test-integration ci ci-fast \
        gen-openapi gen-types openapi-drift-check

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
	@echo "  IaC (ops/ — Terraform + Ansible, ADR-005 §5):"
	@echo "    tf-validate      terraform init -backend=false + validate (ops/terraform)"
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
	@echo "  OpenAPI contract (TASK-019 — offline, no make up required):"
	@echo "    gen-openapi      dump app.openapi() → $(OPENAPI_DUMP) (no server)"
	@echo "    gen-types        regen $(GEN_TYPES) from the committed dump"
	@echo "    openapi-drift-check  gen-openapi + gen-types + git diff --exit-code (fail on drift)"

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

ps:
	$(COMPOSE) ps

sh:
	$(COMPOSE) exec api sh

migrate:
	$(COMPOSE) up --no-deps migration_runner

ansible-unpack:
	cd $(ANSIBLE_DIR) && ANSIBLE_CONFIG=ansible.cfg ansible-playbook playbooks/unpack-env.yml --vault-password-file .vault-pass

# --- IaC (ops/ — Terraform + Ansible) ---
# validate without touching the remote backend (AC2; -backend=false). init
# fetches provider schemas; needs network the first time.
tf-validate:
	terraform -chdir=$(TF_DIR) init -backend=false
	terraform -chdir=$(TF_DIR) validate

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
