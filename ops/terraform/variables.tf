# Input contract. NO secrets hardcoded — sensitive values arrive via TF_VAR_*
# env vars or a gitignored *.tfvars (see terraform.tfvars.example). Secret vars
# are marked `sensitive = true` so they never leak into plan/apply output.

# --- Credentials (secret) ---
variable "do_token" {
  description = "DigitalOcean API token. Supply via TF_VAR_do_token or a gitignored tfvars; NEVER commit."
  type        = string
  sensitive   = true
}

variable "spaces_access_id" {
  description = "Spaces (S3-compatible) access key id for object storage / remote state."
  type        = string
  sensitive   = true
  default     = ""
}

variable "spaces_secret_key" {
  description = "Spaces (S3-compatible) secret key for object storage / remote state."
  type        = string
  sensitive   = true
  default     = ""
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

# --- Object storage (optional; off by default — ADR-005 §5, edge case) ---
variable "enable_object_storage" {
  description = "Create a Spaces bucket for backups/artifacts. Off until a real need appears."
  type        = bool
  default     = false
}

variable "object_storage_bucket" {
  description = "Spaces bucket name (used only when enable_object_storage = true)."
  type        = string
  default     = "trendpulse-backups"
}
