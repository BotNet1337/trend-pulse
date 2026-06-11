# release/Makefile — operator entry point ON THE HOST (style: ironfist).
# Self-contained: operators run ONLY `make -C release <target>`; the bundle never
# references development/ or the root Makefile.
#
# The deploy path goes EXCLUSIVELY through the `render` target — never
# `docker stack deploy -c docker-compose.yml` directly (stack deploy ignores
# include:/env_file:/build:/depends_on.condition). render runs:
#   docker compose ... config | <strip top-level name:> | docker stack deploy -c -
# The rendered config (with inlined secrets) exists only in the pipe, never on disk.
.DEFAULT_GOAL := help

# Recipes use bashisms (herestring, $((...))) — force bash (Ubuntu /bin/sh = dash).
SHELL := /bin/bash

STACK         := trendpulse
PROJECT_NAME  := trendpulse

# Env layering: version.env (image tags) + deploy.env (non-secret) + sensitive.env
# (secrets). deploy.env/sensitive.env are rendered by Ansible (or copied from
# deployment.example for a manual render) — both gitignored.
ENV_DIR       := env
VERSION_ENV   := version.env
DEPLOY_ENV    := $(ENV_DIR)/deploy.env
SENSITIVE_ENV := $(ENV_DIR)/sensitive.env
REQUIRED_ENV  := $(DEPLOY_ENV) $(SENSITIVE_ENV)

COMPOSE := docker compose \
  --project-name $(PROJECT_NAME) \
  --env-file $(VERSION_ENV) \
  --env-file $(DEPLOY_ENV) \
  --env-file $(SENSITIVE_ENV) \
  -f docker-compose.yml

# Standalone backup fragment (NOT in the stack include) — joins the live overlay.
COMPOSE_BACKUP := docker compose \
  --project-name $(PROJECT_NAME)-backup \
  --env-file $(VERSION_ENV) \
  --env-file $(DEPLOY_ENV) \
  --env-file $(SENSITIVE_ENV) \
  -f compose/pg-backup.yml \
  --profile backup

# deploy-wait convergence timeout (seconds).
DEPLOY_WAIT_TIMEOUT ?= 300

# Colors.
RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
CYAN   := \033[0;36m
NC     := \033[0m

.PHONY: help validate render deploy deploy-wait down status logs smoke \
        backup-now restore-check

##@ General

help: ## Display this help message
	@echo "$(CYAN)TrendPulse release bundle — operator targets (run on the host)$(NC)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make -C release $(CYAN)<target>$(NC)\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  $(GREEN)%-14s$(NC) %s\n", $$1, $$2 } \
		/^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo ""

##@ Validation & render

# Env-file presence only — the prerequisite for `render` (compose config needs no
# swarm). All output → stderr so `render` keeps stdout clean for the YAML pipe.
.PHONY: _check-env
_check-env:
	@missing=""; \
	for f in $(REQUIRED_ENV); do \
		if [ ! -f "$$f" ]; then missing="$$missing\n  - $$f"; fi; \
	done; \
	if [ -n "$$missing" ]; then \
		printf "$(RED)Error: required env files are missing:$(NC)$$missing\n" >&2; \
		echo "" >&2; \
		echo "These are rendered by Ansible (env role) on deploy, or copy the" >&2; \
		echo "committed templates for a manual render:" >&2; \
		echo "  cp deployment.example/deploy.env.example    env/deploy.env" >&2; \
		echo "  cp deployment.example/sensitive.env.example env/sensitive.env" >&2; \
		exit 1; \
	fi

validate: _check-env ## Check prerequisites (env files present, docker up, swarm active)
	@printf "$(CYAN)Validating prerequisites...$(NC)\n" >&2
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "$(RED)Error: docker is not installed or not in PATH$(NC)" >&2; exit 1; \
	fi
	@if ! docker info >/dev/null 2>&1; then \
		echo "$(RED)Error: the Docker daemon is not running. Start Docker and retry.$(NC)" >&2; \
		exit 1; \
	fi
	@if [ "$$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null)" != "active" ]; then \
		echo "$(RED)Error: Docker Swarm is not active.$(NC)" >&2; \
		echo "Initialise it (the Ansible provision play does this automatically):" >&2; \
		echo "  docker swarm init --advertise-addr <host-ip>" >&2; \
		exit 1; \
	fi
	@printf "$(GREEN)✓ env files present, Docker up, Swarm active$(NC)\n" >&2

# render: the canonical compose-config → stack-deploy pipeline.
# `compose config` expands include:, inlines env_file: into environment:, and
# interpolates ${...} from the --env-file layers. We strip the top-level `name:`
# key that compose config emits (older docker rejects it in `stack deploy`); we
# touch NOTHING else. The result is piped over stdin — never written to disk.
# Depends only on _check-env (no swarm) so it validates on any machine with env:
#   make render | docker compose -f - config -q   # offline validation method
render: _check-env ## Render the stack YAML to stdout (compose config | strip name: | fix swarm types)
	@$(COMPOSE) config \
		| sed -E '/^name:[[:space:]]/d' \
		| sed -E 's/^([[:space:]]*cpus:[[:space:]]*)([0-9.]+)[[:space:]]*$$/\1"\2"/' \
		| sed -E 's/^([[:space:]]*published:[[:space:]]*)"([0-9]+)"[[:space:]]*$$/\1\2/'

##@ Deploy

deploy: validate ## Render + deploy the stack (waits for convergence)
	@echo "$(CYAN)Deploying stack '$(STACK)' (render | stack deploy)...$(NC)"
	@# --resolve-image never: images are built locally on the host; without this
	@# swarm would try to pull digests from Docker Hub and fail on local tags.
	@# --detach=false: deploy waits for convergence and returns non-zero on failure.
	@# `compose config` coerces types the swarm schema rejects: cpus becomes a bare
	@# number (swarm wants a string) and ports.published becomes a quoted string
	@# (swarm wants an integer). Fix both before piping to stack deploy.
	@$(COMPOSE) config \
		| sed -E '/^name:[[:space:]]/d' \
		| sed -E 's/^([[:space:]]*cpus:[[:space:]]*)([0-9.]+)[[:space:]]*$$/\1"\2"/' \
		| sed -E 's/^([[:space:]]*published:[[:space:]]*)"([0-9]+)"[[:space:]]*$$/\1\2/' \
		| docker stack deploy \
			--compose-file - \
			--detach=false \
			--resolve-image never \
			$(STACK)
	@echo "$(GREEN)✓ stack deploy submitted$(NC)"

deploy-wait: ## Poll until all services converge and all jobs Complete (timeout)
	@echo "$(CYAN)Waiting for stack '$(STACK)' to converge (timeout $(DEPLOY_WAIT_TIMEOUT)s)...$(NC)"
	@deadline=$$(( $$(date +%s) + $(DEPLOY_WAIT_TIMEOUT) )); \
	while :; do \
		not_ready=0; \
		failed_job=""; \
		while read -r name mode replicas; do \
			[ -z "$$name" ] && continue; \
			case "$$mode" in \
				replicated) \
					cur=$${replicas%%/*}; want=$${replicas##*/}; \
					if [ "$$cur" != "$$want" ]; then not_ready=$$((not_ready+1)); fi ;; \
				replicated-job) \
					comp=$$(printf '%s' "$$replicas" | sed -nE 's/.*\(([0-9]+)\/([0-9]+) completed\).*/\1 \2/p'); \
					done_n=$${comp%% *}; want_n=$${comp##* }; \
					if [ -n "$$comp" ] && [ "$$done_n" = "$$want_n" ]; then \
						: ; \
					elif docker service ps --format '{{.CurrentState}}' "$$name" 2>/dev/null | grep -qi 'Complete'; then \
						: ; \
					else \
						not_ready=$$((not_ready+1)); \
					fi ;; \
			esac; \
		done <<< "$$(docker stack services --format '{{.Name}} {{.Mode}} {{.Replicas}}' $(STACK) 2>/dev/null)"; \
		if [ -n "$$failed_job" ]; then \
			echo "$(RED)✗ provisioning job '$$failed_job' FAILED.$(NC)" >&2; \
			docker stack ps --no-trunc $(STACK) >&2; \
			exit 1; \
		fi; \
		if [ "$$not_ready" -eq 0 ]; then \
			echo "$(GREEN)✓ all services running + all jobs Complete$(NC)"; \
			exit 0; \
		fi; \
		if [ "$$(date +%s)" -ge "$$deadline" ]; then \
			echo "$(RED)✗ convergence timed out after $(DEPLOY_WAIT_TIMEOUT)s ($$not_ready not ready).$(NC)" >&2; \
			docker stack ps --no-trunc $(STACK) >&2; \
			exit 1; \
		fi; \
		sleep 5; \
	done

down: ## Remove the stack (docker stack rm)
	@echo "$(CYAN)Removing stack '$(STACK)'...$(NC)"
	@docker stack rm $(STACK)

##@ Operations

status: ## Show stack services + task placement (docker stack ps)
	@docker stack services $(STACK) || true
	@echo ""
	@docker stack ps --no-trunc $(STACK) || true

# logs [SERVICES=api,worker] — follow service logs. Defaults to api.
logs: ## Follow service logs (SERVICES=api,worker; default api)
	@svcs="$(SERVICES)"; [ -z "$$svcs" ] && svcs="api"; \
	for s in $$(echo "$$svcs" | tr ',' ' '); do \
		echo "$(CYAN)--- logs: $(STACK)_$$s ---$(NC)"; \
		docker service logs --follow --tail 100 "$(STACK)_$$s" & \
	done; \
	wait

smoke: ## Run the post-deploy smoke test (HOST=https://domain or http://IP)
	@HOST="$(HOST)" bash scripts/smoke.sh

##@ Backup (TASK-034)

backup-now: validate ## pg_dump → S3 (one-shot; joins the live postgres overlay)
	@$(COMPOSE_BACKUP) run --rm backup_uploader

restore-check: validate ## Download latest dump → throwaway PG → smoke-check (PASS/FAIL)
	@$(COMPOSE_BACKUP) run --rm restore_check; \
	rc=$$?; \
	$(COMPOSE_BACKUP) down --volumes >/dev/null 2>&1 || true; \
	exit $$rc
