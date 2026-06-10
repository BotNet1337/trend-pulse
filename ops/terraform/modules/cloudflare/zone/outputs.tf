output "zone_id" {
  description = "Cloudflare zone ID"
  value       = cloudflare_zone.this.id
}

output "name_servers" {
  description = "Cloudflare nameservers — set these in your domain registrar"
  value       = cloudflare_zone.this.name_servers
}
