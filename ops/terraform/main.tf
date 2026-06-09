# Provider config — vars-driven, no creds in source (CONVENTIONS, ADR-005).
# The token comes from TF_VAR_do_token / gitignored tfvars.
# NOTE: DigitalOcean provider kept for legacy vps/dns/firewall.tf (deprecated, never applied).
provider "digitalocean" {
  token = var.do_token
}

# Hetzner Object Storage via S3-compatible MinIO provider (TASK-056).
# Credentials arrive from gitignored terraform.tfvars (s3_access_key / s3_secret_key).
provider "minio" {
  minio_server   = replace(var.s3_endpoint, "https://", "")
  minio_user     = var.s3_access_key
  minio_password = var.s3_secret_key
  minio_ssl      = true
  minio_region   = var.s3_region
}

# Group all resources under one DO project for tidy state/billing.
resource "digitalocean_project" "trendpulse" {
  name        = var.project_name
  description = "TrendPulse — viral content detector (managed by Terraform, ADR-005)."
  purpose     = "Web Application"
  environment = "Production"

  resources = [
    digitalocean_droplet.edge.urn,
  ]
}
