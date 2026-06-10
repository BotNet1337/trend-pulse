output "zone_id" {
  description = "Cloudflare zone ID for foresignal.biz (feeds environments/prod cloudflare_zone_id)"
  value       = module.zone.zone_id
}

output "nameservers" {
  description = "Cloudflare nameservers — set these in GoDaddy → DNS → Nameservers"
  value       = module.zone.name_servers
}

output "email_addresses" {
  description = "Configured forwarding email addresses"
  value       = module.email_routing.configured_addresses
}

# Empty until sentry_enabled=true. Copy into the ansible vault as
# vault_sentry_dsn: `terraform output -raw sentry_dsn`.
output "sentry_dsn" {
  description = "Sentry DSN — set as vault_sentry_dsn / SENTRY_DSN"
  value       = var.sentry_enabled ? module.sentry[0].dsn : ""
}
