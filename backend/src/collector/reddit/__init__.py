"""Reddit source adapter (TASK-092, ADR-001).

Mirrors `collector/twitter/`: a `RedditCollector` implementing the SDK-free
`SourceCollector` port over the Reddit OAuth2 application-only API. Token refresh,
rate-limiting and 429 backoff are encapsulated INSIDE the collector and never
surface through the port (ADR-001 invariant). Reddit read-only public access is
FREE — there is no pay-per-use read budget (unlike the Twitter source).
"""
