# TrendPulse — Docs Vault

This `docs/` tree is the source of truth for product + architecture of **TrendPulse**
(персональный детектор вирусного контента из Telegram). Read it before planning; do not
derive patterns from general knowledge.

## Map

- **Product:** [`product/overview.md`](./product/overview.md) — what it is, architecture, monetization, roadmap, compliance.
- **Conventions:** [`CONVENTIONS.md`](./CONVENTIONS.md) — coding hard rules (enforced by `trendpulse-review` + the forbidden-patterns hook).
- **Codemaps:** [`CODEMAPS/`](./CODEMAPS/) — structural maps to read first (modules, tasks/queues, events).
- **Tasks:** [`tasks/`](./tasks/) — surgical-change task docs + [`tasks/tasks-index.md`](./tasks/tasks-index.md).
- **Architecture:** [`architecture/`](./architecture/):
  - [`high-level-architecture.md`](./architecture/high-level-architecture.md) — system context, **component diagram, user flow, data flow** (mermaid).
  - [`network-design.md`](./architecture/network-design.md) — сегментация сетей (edge/internal/per-infra), nginx-only-edge.
  - [`build-and-release.md`](./architecture/build-and-release.md) — сборка/ассемблирование + **future ORAS → `release` bundle**.
  - ADRs: [001 source-abstraction](./architecture/adr-001-source-abstraction.md), [002 multi-tenancy](./architecture/adr-002-multi-tenancy-and-queues.md), [003 monorepo+auth (fastapi-users)](./architecture/adr-003-monorepo-and-auth.md), [004 crypto-billing (NOWPayments)](./architecture/adr-004-crypto-billing-nowpayments.md), [005 infra+secrets](./architecture/adr-005-infra-provisioning-and-secrets.md), [006 packaging/ORAS](./architecture/adr-006-packaging-and-release.md).
- **Learnings:** [`learnings.md`](./learnings.md) — append-only ledger, distilled into agent memory.

## Working model — two layers

1. **Greenfield / planning** (BMM flow): `bmad-product-brief` → `bmad-prd` → `bmad-create-architecture` → `bmad-create-epics-and-stories` → `bmad-dev-story`. Artifacts land in `_bmad-output/`.
2. **Surgical changes** (`/trendpulse-*`): `trendpulse-plan` → `trendpulse-executor` (locate → do(TDD) → verify(G2) → review → security? → ship → learnings). State + resume live in the task doc's Checkpoints block.

Project root for both = `apps/trendPulse`. Communicate in Russian.
