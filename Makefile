# apps/trendPulse/Makefile — THE single entry point (ADR-005 §1, CONVENTIONS).
# Use `make up`, never `make -C development ...` or raw `docker compose`/`uv`.
#
# Docker targets wrap compose with --env-file version.env (image/build-arg pins)
# + the top per-service compose file. Dev/CI targets wrap `uv run` in backend/.

COMPOSE := docker compose --env-file development/version.env -f development/docker-compose.yml
UV      := uv run --directory backend
INFRA   := postgres redis pg_vector_provisioner migration_runner
# IaC dirs (ADR-005 §5). Ansible runs with cwd = ops/ansible so ansible.cfg +
# .vault-pass (gitignored dev vault password) resolve relative to it.
ANSIBLE_DIR := ops/ansible
TF_DIR      := ops/terraform

.PHONY: help up dev-up dev-infra-up down build logs ps restart sh migrate \
        ansible-unpack tf-validate ansible-lint ansible-check \
        lint fmt typecheck test test-integration ci ci-fast

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
	@echo "    ci               fmt-check + lint + typecheck + FULL test"
	@echo "    ci-fast          fmt-check + lint + typecheck + test (not integration)"

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
	$(UV) pytest

ci-fast:
	$(UV) ruff format --check .
	$(UV) ruff check .
	$(UV) mypy
	$(UV) pytest -m 'not integration'
