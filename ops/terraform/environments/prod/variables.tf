# ============================================================
# Hetzner
# ============================================================

variable "hetzner_api_token" {
  description = "Hetzner Cloud API token. Get from: https://console.hetzner.cloud → project TrendPulse → Security → API Tokens → Generate (Read & Write)"
  type        = string
  sensitive   = true
}

variable "server_type" {
  description = "Hetzner server type (cx23 = 2 vCPU / 4GB / 40GB; cx33 = 4 vCPU / 8GB / 80GB). Check availability: api.hetzner.cloud/v1/server_types — Hetzner retires generations (cx22/cx32 → cx23/cx33)."
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Hetzner datacenter (nbg1 = Nuremberg, fsn1 = Falkenstein, hel1 = Helsinki)"
  type        = string
  default     = "nbg1"
}

variable "deploy_user" {
  description = "Username for deployment (Ansible inventory ansible_user)"
  type        = string
  default     = "deploy"
}

variable "ssh_public_key" {
  description = "SSH public key for the deploy user"
  type        = string
}

variable "ssh_allowed_ips" {
  description = "CIDRs allowed to SSH (restrict to your IP for least privilege)"
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

# ============================================================
# Cloudflare
# ============================================================

variable "cloudflare_api_token" {
  description = "Cloudflare API token with DNS edit permissions (same as environments/org)"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for foresignal.biz. Get from: cd ../org && terraform output -raw zone_id"
  type        = string
}

variable "domain" {
  description = "Root domain"
  type        = string
  default     = "foresignal.biz"
}

# ============================================================
# Hetzner Object Storage (S3-compatible, TASK-056 — backups)
# ============================================================

variable "s3_endpoint" {
  description = "Hetzner Object Storage endpoint URL, e.g. https://nbg1.your-objectstorage.com (region: fsn1 / nbg1 / hel1)"
  type        = string
}

variable "s3_region" {
  description = "Hetzner Object Storage region identifier. Must match the datacenter slug in s3_endpoint (fsn1 / nbg1 / hel1 — NOT 'eu-central')"
  type        = string
  default     = "nbg1"
}

variable "s3_access_key" {
  description = "Hetzner Object Storage access key. Hetzner Console → project TrendPulse → Object Storage → Manage credentials"
  type        = string
  sensitive   = true
}

variable "s3_secret_key" {
  description = "Hetzner Object Storage secret key (created alongside s3_access_key)"
  type        = string
  sensitive   = true
}

variable "s3_backup_bucket_name" {
  description = "Name of the S3 backup bucket on Hetzner Object Storage"
  type        = string
  default     = "trendpulse-backups"
}

variable "backup_expire_after_days" {
  description = "Days after which postgres/ backup objects are expired by the bucket lifecycle rule"
  type        = number
  default     = 30
}
