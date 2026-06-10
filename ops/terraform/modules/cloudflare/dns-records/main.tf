terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

# ============================================================
# DNS A-records → server IP
# ============================================================

resource "cloudflare_dns_record" "a_records" {
  for_each = var.records

  zone_id = var.zone_id
  name    = each.value.name
  type    = "A"
  content = var.server_ip
  ttl     = each.value.ttl
  proxied = each.value.proxied
}
