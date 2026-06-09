# Input contract. NO secrets hardcoded — sensitive values arrive via TF_VAR_*
# env vars or a gitignored *.tfvars (see terraform.tfvars.example). Secret vars
# are marked `sensitive = true` so they never leak into plan/apply output.

# --- Credentials (secret) ---
variable "do_token" {
  description = "DigitalOcean API token (legacy — used by deprecated vps/dns/firewall.tf). Supply via TF_VAR_do_token or a gitignored tfvars; NEVER commit."
  type        = string
  sensitive   = true
  default     = ""
}

# --- Hetzner Object Storage (S3-compatible, TASK-056) ---
variable "s3_endpoint" {
  description = "Hetzner Object Storage endpoint URL, e.g. https://fsn1.your-objectstorage.com (region: fsn1 / nbg1 / hel1)."
  type        = string
}

variable "s3_region" {
  description = "Hetzner Object Storage region identifier used by the minio provider. Must match the datacenter slug in s3_endpoint (e.g. fsn1, nbg1, hel1 — NOT 'eu-central')."
  type        = string
  default     = "fsn1"
}

variable "s3_access_key" {
  description = "Hetzner Object Storage access key. Create in Hetzner Console → project TrendPulse → Object Storage → Manage credentials. Supply via gitignored tfvars; NEVER commit."
  type        = string
  sensitive   = true
}

variable "s3_secret_key" {
  description = "Hetzner Object Storage secret key. Create alongside s3_access_key. Supply via gitignored tfvars; NEVER commit."
  type        = string
  sensitive   = true
}

variable "s3_backup_bucket_name" {
  description = "Name of the S3 backup bucket created on Hetzner Object Storage."
  type        = string
  default     = "trendpulse-backups"
}

variable "backup_expire_after_days" {
  description = "Days after which postgres/ backup objects are expired by the bucket lifecycle rule."
  type        = number
  default     = 30
}

# --- Placement / sizing (non-secret) ---
variable "region" {
  description = "DigitalOcean region slug (e.g. fra1)."
  type        = string
  default     = "fra1"
}

variable "vps_size" {
  description = "Droplet size slug for the edge/app host."
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "vps_image" {
  description = "Base image slug for the droplet."
  type        = string
  default     = "ubuntu-24-04-x64"
}

variable "project_name" {
  description = "Logical name prefix for created resources."
  type        = string
  default     = "trendpulse"
}

# --- DNS ---
variable "domain" {
  description = "Apex domain managed for the app (e.g. trendpulse.example)."
  type        = string
}

variable "app_subdomain" {
  description = "Subdomain record for the app/edge (relative to domain). Empty = apex."
  type        = string
  default     = "app"
}

# --- SSH / firewall allowlist (AC7, network-design) ---
variable "ssh_key_fingerprints" {
  description = "DigitalOcean SSH key fingerprints injected into the droplet."
  type        = list(string)
  default     = []
}

variable "ssh_allowlist_cidrs" {
  description = "CIDRs permitted to reach SSH (port 22). Least-privilege: NOT 0.0.0.0/0."
  type        = list(string)
  # Sentinel default; override per environment. Documented in terraform.tfvars.example.
  default = ["127.0.0.1/32"]
}

