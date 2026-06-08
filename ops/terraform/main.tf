# Provider config — vars-driven, no creds in source (CONVENTIONS, ADR-005).
# The token comes from TF_VAR_do_token / gitignored tfvars. Spaces creds (for
# the optional object storage / S3-compatible remote state) are passed the same way.
provider "digitalocean" {
  token             = var.do_token
  spaces_access_id  = var.spaces_access_id
  spaces_secret_key = var.spaces_secret_key
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
