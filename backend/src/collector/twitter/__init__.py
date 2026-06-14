"""Twitter/X source adapter (TASK-031, ADR-001).

Mirrors `collector/telegram/`: a `TwitterCollector` implementing the SDK-free
`SourceCollector` port over the X API v2. Rate-limiting, 429 backoff and the
pay-per-use monthly read budget are encapsulated INSIDE the collector and never
surface through the port (ADR-001 invariant).
"""
