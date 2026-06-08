---
name: trendpulse-security
description: Conditional security stage for TrendPulse surgical changes. Dispatched by trendpulse-executor when the change touches authentication, authorization, user input, secrets, OAuth, crypto, or external API surfaces. Usable standalone ("проверь безопасность", "security review"). Reviews the diff for OWASP-class issues and project-specific risks; returns severity-triaged findings.
---

# TrendPulse Security (conditional stage)

Runs only when the change touches a security-sensitive surface. Trigger signals: anything under IAM/auth, guards/decorators, OAuth flows (PKCE, callbacks, token storage/refresh), input validation/Pydantic boundaries, secrets/env, crypto, file upload/S3, public API endpoints, raw SQL / SQLAlchemy text().

## Do

<workflow>
  <step n="1" goal="Decide if security applies">
    <action>If the diff touches none of the trigger surfaces → return `status: skipped`.</action>
  </step>
  <step n="2" goal="Review the diff">
    <action>Prefer dispatching the `security-reviewer` agent over the diff (`git diff` vs baseline_commit). Check: authz on every new/changed endpoint (semantic guard decorator, not raw), input validated at the boundary (Pydantic models/Depends guards, no trust of external data), no secrets hardcoded, OAuth scopes/PKCE/callback/token-refresh correct, no SQL injection in SQLAlchemy (bind params, never f-string SQL), error messages don't leak internals, rate-limiting where required.</action>
    <action>Cross-check project rules: secrets via env/secret-manager (never a Telethon `session_string` for a user account — only the technical-account pool, per the product compliance rules), TTL/URLs via pydantic-settings/env, error responses don't leak stack/internals. Confirm raw post content is not persisted beyond the 48h retention window and only public channels are read.</action>
  </step>
  <step n="3" goal="Triage">
    <action>Classify findings CRITICAL/HIGH/MEDIUM/LOW. CRITICAL/HIGH are blocking — route back to do/debug; rotate any exposed secret.</action>
  </step>
</workflow>

## Return

```
status: pass | blocked | skipped
findings:
  - severity: CRITICAL|HIGH|MEDIUM|LOW
    category: authz|input|secret|oauth|injection|crypto|leak|rate-limit
    where: <file:line>
    what: <issue>
    fix: <remedy>
```
