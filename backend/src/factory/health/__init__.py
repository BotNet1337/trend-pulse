"""Pre-promote health probes for the account factory (TASK-141, Layer B-proxy).

`base` defines the `HealthProbe` Protocol + `HealthResult` DTO; `fake` is the
deterministic CI impl; `telethon` is the real Telethon-backed probe (lazy import,
config-gated, never exercised over the network in CI) that reads a public channel
through the account's OWN session + proxy; `factory` selects the impl by env (real
ONLY when telegram creds + a real provider + a probe channel are all set, else fake).
"""
