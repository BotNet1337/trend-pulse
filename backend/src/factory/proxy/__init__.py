"""Dynamic proxy providers for the account factory (TASK-139, Layer B-proxy).

`base` defines the `ProxyProvider` Protocol + `ProxyLease` DTO; `fake` is the
deterministic CI impl; `mobileproxy` is the real httpx-backed Mobileproxy.space
client; `factory` selects the impl by env (`ACCOUNT_FACTORY_PROXY_PROVIDER`). Unset
→ `None` (the caller keeps today's static-pool path — zero behavior change).
"""
