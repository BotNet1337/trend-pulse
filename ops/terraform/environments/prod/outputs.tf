output "server_ip" {
  description = "Production server public IPv4 (target for the Ansible prod inventory)"
  value       = module.server.server_ip
}

output "server_ipv6" {
  description = "Production server public IPv6"
  value       = module.server.server_ipv6
}

output "deploy_user" {
  description = "Deploy username for SSH/Ansible"
  value       = module.server.deploy_user
}

output "app_fqdn" {
  description = "Fully-qualified app hostname"
  value       = "app.${var.domain}"
}

output "dns_records" {
  description = "Created DNS record hostnames"
  value       = module.dns.record_hostnames
}

output "backup_bucket_name" {
  description = "Hetzner Object Storage backup bucket name"
  value       = module.backup_storage.bucket_name
}

output "s3_endpoint" {
  description = "Hetzner Object Storage endpoint URL"
  value       = var.s3_endpoint
}

output "s3_region" {
  description = "Hetzner Object Storage region identifier"
  value       = var.s3_region
}
