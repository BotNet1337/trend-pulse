# TrendPulse — Codemaps

Structural maps read first by `trendpulse-locate` / `trendpulse-plan` to place a change
correctly and assess blast radius. Fill these in as the code lands.

Planned maps:

- `modules.md` — `api/`, `collector/`, `pipeline/`, `storage/`, `alerts/` and their public service interfaces.
- `tasks.md` — Celery tasks, queues (`batch:user_{id}`, `score:global`), Beat schedule, retry/`max_instances` rules.
- `data.md` — Postgres tables (`users`, `watchlists`, `clusters`, `scores`, `alerts`), pgvector dims, Alembic migrations.
- `pipeline.md` — batch flow `dedup → normalize → embed → cluster` and the scorer.

_(empty — no code yet; create these alongside the first modules)_
