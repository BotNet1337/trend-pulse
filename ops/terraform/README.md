# ops/terraform — IaC for external services

Per [ADR-005](../../docs/architecture/adr-005-infra-provisioning-and-secrets.md) §5,
Terraform provisions the **external/edge surface** (provision step); Ansible
configures the host (configure step). Boundary: TF → cloud state, Ansible → state
inside the VPS.

Provider: **DigitalOcean** (`digitalocean/digitalocean`) — droplet, cloud
firewall, DNS, and (optional) Spaces object storage.

## Files

| File | Purpose |
|---|---|
| `versions.tf` | `required_version` + pinned provider versions |
| `main.tf` | provider config (vars-driven, no creds) + DO project |
| `backend.tf` | remote state (S3-compatible Spaces); creds via `-backend-config`/env |
| `variables.tf` | inputs; secrets marked `sensitive = true` |
| `vps.tf` | edge/app droplet |
| `firewall.tf` | **only 443 + 80 + SSH-allowlist** ingress (mirrors network-design) |
| `dns.tf` | A record → edge droplet |
| `object_storage.tf` | optional Spaces bucket (`enable_object_storage`, off by default) |
| `outputs.tf` | `edge_ipv4`, `app_fqdn`, `firewall_id` |
| `terraform.tfvars.example` | sample inputs (NO secrets) |

## Validate (offline-friendly, no backend)

```bash
make tf-validate
# = terraform -chdir=ops/terraform init -backend=false && terraform validate
```

## Secrets & state

- No secrets in `*.tf`. Supply via `TF_VAR_do_token`, `TF_VAR_spaces_*`, or a
  **gitignored** `terraform.tfvars`. Sensitive vars carry `sensitive = true`.
- Remote state in Spaces; backend creds passed at `init` time
  (`-backend-config=...`), never in `backend.tf`. `*.tfstate*` is gitignored.

## Firewall (AC7)

Ingress is restricted to: `80/tcp` (→ redirect to 443 at nginx), `443/tcp`, and
`22/tcp` limited to `ssh_allowlist_cidrs` (NOT `0.0.0.0/0`). Postgres/Redis get
no rule — they are compose-internal networks and never published.
