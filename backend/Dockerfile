# App image for api/beat (lean: core only) and worker (core + `ml`). `--no-dev`
# always excludes dev tooling (pytest/ruff/mypy). The `ml` group (sentence-
# transformers/torch) is installed ONLY when INSTALL_ML=true — the worker image
# needs it for the embed pipeline (task-007); api/beat stay lean (task-001
# invariant: torch off the api boot path). Build args set per-service in compose.
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.12
ARG INSTALL_ML=false

# Pinned uv as its own stage — buildkit forbids variable expansion directly in
# `COPY --from=<image:${tag}>`, so reference the version via a named FROM stage.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm

# uv installs into the project venv; vendor it from the pinned uv stage.
COPY --from=uv /uv /uvx /usr/local/bin/

# git is needed by some build backends / VCS deps; psycopg uses the binary wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Put the project venv on PATH so `uvicorn`/`celery`/`alembic` resolve directly.
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

# Re-declare after FROM so the build arg is in scope for the RUN layers.
# `--group ml` is appended only when INSTALL_ML=true (worker image).
ARG INSTALL_ML=false

# Layer 1: dependencies only (cached unless lock changes). --frozen requires a
# committed uv.lock; generate it with `uv lock` before building.
COPY pyproject.toml uv.lock ./
RUN if [ "$INSTALL_ML" = "true" ]; then ML="--group ml"; else ML=""; fi; \
    uv sync --frozen --no-install-project --no-dev $ML

# Layer 2: source + alembic, then install the project itself.
COPY src/ src/
COPY alembic.ini ./
COPY migrations/ migrations/
RUN if [ "$INSTALL_ML" = "true" ]; then ML="--group ml"; else ML=""; fi; \
    uv sync --frozen --no-dev $ML
