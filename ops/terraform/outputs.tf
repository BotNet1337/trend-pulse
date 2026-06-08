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

output "object_storage_bucket" {
  description = "Spaces bucket name when object storage is enabled, else empty."
  value       = var.enable_object_storage ? var.object_storage_bucket : ""
}
