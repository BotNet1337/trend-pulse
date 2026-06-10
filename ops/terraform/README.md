# TrendPulse — Terraform

Infrastructure as Code for TrendPulse. Modular architecture grouped by provider
(same layout as postbridge/ops/terraform). Per
[ADR-005](../../docs/architecture/adr-005-infra-provisioning-and-secrets.md) §5,
Terraform provisions the **external/edge surface**; Ansible configures the host.

## Structure

```
terraform/
  modules/
    cloudflare/
      zone/                    # Cloudflare zone (DNS delegation from GoDaddy)
      email-routing/           # Inbound forwarding (SPF, DMARC, catch-all) + Resend DNS
      dns-records/             # DNS A-records → server IP
    hetzner/
      server/                  # VPS + cloud-init (Docker, UFW, fail2ban, deploy user)
      object-storage/          # S3 bucket + versioning + backup lifecycle (TASK-056)
  environments/
    org/                       # Organization-level: foresignal.biz zone + email (Cloudflare)
    prod/                      # Production: Hetzner VPS + Cloudflare DNS + backup bucket
```

### Principles

- **Modules = building blocks.** Each module does one thing. Grouped by provider.
- **Environments = composition.** Each environment assembles modules like a mosaic.
- **No "just in case" resources.** New environments (staging, …) appear as new directories when needed.

## Setup Order

### 1. Organization (`environments/org/`)

Cloudflare zone for `foresignal.biz` (registered at GoDaddy) + email forwarding.

| Variable | How to get |
|----------|-----------|
| `cloudflare_api_token` | [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → Custom token: Account Settings:Read, Zone:Edit, DNS:Edit, Email Routing Rules:Edit; Zone Resources: All zones |
| `cloudflare_account_id` | Cloudflare Dashboard → Account Home (right sidebar / URL) |

```bash
cd environments/org
cp terraform.tfvars.example terraform.tfvars   # fill in
terraform init && terraform apply
./save-outputs.sh
```

After apply: GoDaddy → foresignal.biz → DNS → **Nameservers → Change** → enter the
two Cloudflare NS from the output. Propagation: 15 min – a few hours.

### 2. Production (`environments/prod/`)

Hetzner VPS + Cloudflare A-records (`foresignal.biz`, `app.foresignal.biz`) + backup bucket.

| Variable | How to get |
|----------|-----------|
| `hetzner_api_token` | [console.hetzner.cloud](https://console.hetzner.cloud) → project TrendPulse → Security → API Tokens → Generate (Read & Write) |
| `ssh_public_key` | `cat ~/.ssh/id_ed25519.pub` |
| `cloudflare_api_token` | same as org/ |
| `cloudflare_zone_id` | `cd ../org && terraform output -raw zone_id` |
| `s3_access_key` / `s3_secret_key` | Hetzner Console → project TrendPulse → Object Storage → Manage credentials |

```bash
cd environments/prod
cp terraform.tfvars.example terraform.tfvars   # fill in
terraform init && terraform apply
./save-outputs.sh   # prints server IP + ready Ansible inventory snippet
```

After apply:
- `ssh deploy@<server_ip>` (wait ~2 min for cloud-init: Docker, UFW, fail2ban)
- DNS A-records are created automatically in Cloudflare
- Create `ops/ansible/inventory/prod.yml` from the `save-outputs.sh` snippet

## Modules

| Module | Provider | Description |
|--------|----------|-------------|
| `cloudflare/zone` | Cloudflare | Zone creation, DNS delegation |
| `cloudflare/email-routing` | Cloudflare | SPF, DMARC, catch-all, named addresses; Resend DKIM/SPF/MX (flag-gated) |
| `cloudflare/dns-records` | Cloudflare | A-records pointing to the server IP |
| `hetzner/server` | Hetzner | VPS + firewall (22/80/443) + cloud-init (Docker, UFW, deploy user) |
| `hetzner/object-storage` | MinIO (Hetzner S3) | Backup bucket + versioning + `postgres/` lifecycle expiry |

## Secrets & state

- No secrets in `*.tf`. Real values live in **gitignored** `terraform.tfvars` per
  environment (or `TF_VAR_*` env vars). Sensitive vars carry `sensitive = true`.
- State is local per environment and gitignored (`*.tfstate*`). The pre-restructure
  bucket state was migrated to `environments/prod/terraform.tfstate` (module address
  `module.backup_storage` is unchanged — do not rename).
- The same S3 credentials must also reach the prod host via Ansible vault
  (`vault_s3_access_key` / `vault_s3_secret_key`) — there is no auto-sync from tfvars.

## Validate (offline-friendly)

```bash
make tf-validate
# = terraform -chdir=environments/{org,prod} init -backend=false && validate
```

## Firewall (AC7)

Public ingress is restricted to `80/tcp` (→ 443 redirect at nginx), `443/tcp`, and
`22/tcp` (optionally limited via `ssh_allowed_ips`) — both at the Hetzner cloud
firewall and host UFW. Postgres/Redis get no rule — they are compose-internal
networks and never published.
