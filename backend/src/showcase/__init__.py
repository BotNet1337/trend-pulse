"""Showcase autoposting module (TASK-044).

Beat task that posts top showcase-tenant signals to a public TG channel with
delay + CTA + anti-spam. See task doc for full design rationale.

Public modules:
- constants   : task name constant (leaf — no celery import).
- selection   : pure candidate filtering (score/age/window/dedup/daily-cap).
- formatting  : post text builder + topic sanitization helper.
- sender      : httpx sendMessage wrapper (best-effort, never raises).
- tasks       : Celery beat task body (INSERT-first idempotency, no-op if no creds).
"""
