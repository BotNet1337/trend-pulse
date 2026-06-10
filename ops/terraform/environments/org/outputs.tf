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
