# ops/terraform — IaC for external services

Per [ADR-005](../../docs/architecture/adr-005-infra-provisioning-and-secrets.md) §5,
Terraform provisions the **external/edge surface** (provision step); Ansible
configures the host (configure step). Boundary: TF → cloud state, Ansible → state
inside the VPS.

## Providers

- **DigitalOcean** (`digitalocean/digitalocean ~> 2.40`) — legacy vps/dns/firewall files (see note below).
- **MinIO / Hetzner Object Storage** (`aminueza/minio ~> 3.0`) — S3-compatible object storage for backups (TASK-056).

## Files

| File | Purpose |
|---|---|
| `versions.tf` | `required_version` + pinned provider versions |
| `main.tf` | provider configs (vars-driven, no creds) + DO project |
| `backend.tf` | remote state (S3-compatible); creds via `-backend-config`/env |
| `variables.tf` | inputs; secrets marked `sensitive = true` |
| `object_storage.tf` | Hetzner backup bucket via `modules/hetzner/object-storage` |
| `outputs.tf` | `edge_ipv4`, `app_fqdn`, `firewall_id`, `backup_bucket_name`, `s3_endpoint`, `s3_region` |
| `terraform.tfvars.example` | sample inputs (NO secrets) |
| `modules/hetzner/object-storage/` | reusable module: S3 bucket + versioning + lifecycle |

> **Deprecated (never applied — no tfstate):** `vps.tf`, `dns.tf`, `firewall.tf` are legacy
> DigitalOcean resources. The real production host is **Hetzner**. These files are kept intact
> for reference but have never been applied. Porting them to Hetzner follows the pattern in
> [`postbridge/ops/terraform/modules/hetzner/server`](../../../postbridge/ops/terraform/modules/hetzner/server)
> — that is a separate task when needed.

## Object Storage (Hetzner)

### Getting credentials

1. Log in to [Hetzner Cloud Console](https://console.hetzner.cloud).
2. Switch to the **TrendPulse** project (separate from postbridge — do NOT reuse postbridge credentials).
3. Go to **Object Storage → Manage credentials**.
4. Generate a new Access Key / Secret Key pair.
5. Add to `ops/terraform/terraform.tfvars` (gitignored):
   ```
   s3_access_key = "<your access key>"
   s3_secret_key = "<your secret key>"
   ```

### Duplicate keys into Ansible vault

The same credentials must also reach the prod host via Ansible. After generating
S3 credentials:

1. Add `vault_s3_access_key` and `vault_s3_secret_key` to `ops/ansible/vault/sensitive.vault.yml`.
2. Run `make ansible-unpack` to render `sensitive.env` (includes `S3_ACCESS_KEY`/`S3_SECRET_KEY`).

This is a manual step — there is no auto-sync from tfvars to vault (see ADR-005).

## Validate (offline-friendly, no backend)

```bash
make tf-validate
# = terraform -chdir=ops/terraform init -backend=false && terraform validate
```

## Secrets & state

- No secrets in `*.tf`. Supply via `TF_VAR_s3_access_key`, `TF_VAR_s3_secret_key`, or a
  **gitignored** `terraform.tfvars`. Sensitive vars carry `sensitive = true`.
- Remote state in S3-compatible storage; backend creds passed at `init` time
  (`-backend-config=...`), never in `backend.tf`. `*.tfstate*` is gitignored.

## Firewall (AC7)

Ingress is restricted to: `80/tcp` (→ redirect to 443 at nginx), `443/tcp`, and
`22/tcp` limited to `ssh_allowlist_cidrs` (NOT `0.0.0.0/0`). Postgres/Redis get
no rule — they are compose-internal networks and never published.
