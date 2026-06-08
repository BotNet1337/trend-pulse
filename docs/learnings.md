# TrendPulse — Learnings Ledger

Append-only. Stage 7 of `trendpulse-executor` writes one dated block per run.
`trendpulse-distill-learnings` periodically promotes durable lessons into agent memory
and marks promoted blocks with `<!-- promoted: <names> (YYYY-MM-DD) -->`.

Block format:

```
## YYYY-MM-DD — TASK-NNN <title>
- **Lesson:** … **Why:** … **How to apply:** …
- **Decision:** … **Rationale:** …
- **Gotcha:** …
```

---

<!-- learnings start below -->
