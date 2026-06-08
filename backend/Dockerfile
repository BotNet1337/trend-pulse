# Single application image for api/worker/beat — they differ ONLY by command
# (set in the per-service compose files). Runtime image carries ONLY core deps:
# `--no-dev` excludes the `dev` group (pytest/ruff/mypy/pre-commit) and `ml`
# (torch) is non-default, so neither lands in the shipped image. Dev tooling runs
# on the host via `make ci`/`uv run`, never in the container.
ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.12

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

# Layer 1: dependencies only (cached unless lock changes). --frozen requires a
# committed uv.lock; generate it with `uv lock` before building.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Layer 2: source + alembic, then install the project itself.
COPY src/ src/
COPY alembic.ini ./
COPY migrations/ migrations/
RUN uv sync --frozen --no-dev
