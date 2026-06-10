output "configured_addresses" {
  description = "Email addresses configured for routing"
  value       = [for k, v in var.email_routes : "${k}@${var.domain}"]
}

output "resend_dns_records" {
  description = "Resend DNS records created"
  value = var.resend_enabled ? {
    dkim = length(cloudflare_dns_record.resend_dkim) > 0 ? cloudflare_dns_record.resend_dkim[0].name : null
    spf  = length(cloudflare_dns_record.resend_spf) > 0 ? cloudflare_dns_record.resend_spf[0].name : null
    mx   = length(cloudflare_dns_record.resend_mx) > 0 ? cloudflare_dns_record.resend_mx[0].name : null
  } : null
}
