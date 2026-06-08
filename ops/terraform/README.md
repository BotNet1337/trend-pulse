# ops/terraform — IaC for external services (skeleton)

Real implementation lands in **task-012** (per ADR-005 §5). This directory will
manage the external/edge surface as code:

- DNS records (app + webhook hostnames)
- VPS / cloud provider provisioning
- Firewall / edge rules (only 443, +80 redirect — matches network-design.md)
- TLS certificate issuance/renewal (certs mounted into the nginx edge service)

Nothing here is wired into `make` yet; task-001 only establishes the layout.
