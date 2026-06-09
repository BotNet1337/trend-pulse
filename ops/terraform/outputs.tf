# Outputs consumed by operators / the Ansible inventory (edge droplet IP feeds
# the prod host). No secrets exported.
output "edge_ipv4" {
  description = "Public IPv4 of the edge droplet (target for Ansible prod inventory)."
  value       = digitalocean_droplet.edge.ipv4_address
}

output "app_fqdn" {
  description = "Fully-qualified app hostname."
  value       = var.app_subdomain == "" ? var.domain : "${var.app_subdomain}.${var.domain}"
}

output "firewall_id" {
  description = "ID of the edge firewall (443/80/SSH-allowlist only)."
  value       = digitalocean_firewall.edge.id
}

# --- Object storage (TASK-056) ---
output "backup_bucket_name" {
  description = "Hetzner Object Storage backup bucket name."
  value       = module.backup_storage.bucket_name
}

output "s3_endpoint" {
  description = "Hetzner Object Storage endpoint URL."
  value       = var.s3_endpoint
}

output "s3_region" {
  description = "Hetzner Object Storage region identifier."
  value       = var.s3_region
}
