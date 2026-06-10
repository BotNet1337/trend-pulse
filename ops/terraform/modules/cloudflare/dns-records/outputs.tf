output "record_ids" {
  description = "Map of record key → Cloudflare record ID"
  value       = { for k, r in cloudflare_dns_record.a_records : k => r.id }
}

output "record_hostnames" {
  description = "Map of record key → FQDN"
  value       = { for k, r in cloudflare_dns_record.a_records : k => r.name }
}
