terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

# Zone-level Email Routing enablement + Cloudflare-managed MX records:
# `cloudflare_email_routing_dns` calls the enable-DNS endpoint, which provisions
# the route1/2/3.mx.cloudflare.net MX set and flips the zone's routing status to
# Enabled (2026-06-12: routing was never enabled — rules existed but every mail
# was dropped; the old comment claimed this is dashboard-only, provider v5 can).
# Destination address VERIFICATION stays manual (confirmation e-mail click).

resource "cloudflare_email_routing_dns" "routing" {
  zone_id = var.zone_id
  name    = var.domain
}

# --- SPF record (root domain) ---
# Includes Cloudflare for email routing. Resend uses a "send" subdomain for SPF.

resource "cloudflare_dns_record" "spf" {
  zone_id = var.zone_id
  name    = var.domain
  type    = "TXT"
  content = "v=spf1 include:_spf.mx.cloudflare.net ~all"
  ttl     = 1
}

# --- DMARC record ---

resource "cloudflare_dns_record" "dmarc" {
  zone_id = var.zone_id
  name    = "_dmarc.${var.domain}"
  type    = "TXT"
  content = var.dmarc_rua_email != "" ? "v=DMARC1; p=${var.dmarc_policy}; rua=mailto:${var.dmarc_rua_email}" : "v=DMARC1; p=${var.dmarc_policy};"
  ttl     = 1
}

# --- Email routing catch-all rule ---

resource "cloudflare_email_routing_catch_all" "catch_all" {
  zone_id = var.zone_id
  name    = "Catch-all → ${var.catch_all_destination}"
  enabled = var.catch_all_enabled

  matchers = [{
    type = "all"
  }]

  actions = [{
    type  = "forward"
    value = [var.catch_all_destination]
  }]
}

# --- Individual email routing rules ---

resource "cloudflare_email_routing_rule" "addresses" {
  for_each = var.email_routes

  zone_id = var.zone_id
  name    = "${each.key}@${var.domain} → ${each.value}"
  enabled = true

  matchers = [{
    type  = "literal"
    field = "to"
    value = "${each.key}@${var.domain}"
  }]

  actions = [{
    type  = "forward"
    value = [each.value]
  }]
}

# ============================================================
# Resend — DKIM + SPF + MX for sending subdomain
# ============================================================

# DKIM (TXT record on resend._domainkey)
resource "cloudflare_dns_record" "resend_dkim" {
  count = var.resend_enabled ? 1 : 0

  zone_id = var.zone_id
  name    = "resend._domainkey.${var.domain}"
  type    = "TXT"
  content = var.resend_dkim_value
  ttl     = 1
}

# SPF for send subdomain (TXT)
resource "cloudflare_dns_record" "resend_spf" {
  count = var.resend_enabled ? 1 : 0

  zone_id = var.zone_id
  name    = "${var.resend_spf_subdomain}.${var.domain}"
  type    = "TXT"
  content = "v=spf1 include:amazonses.com ~all"
  ttl     = 1
}

# MX for send subdomain (for bounce handling)
resource "cloudflare_dns_record" "resend_mx" {
  count = var.resend_enabled ? 1 : 0

  zone_id  = var.zone_id
  name     = "${var.resend_spf_subdomain}.${var.domain}"
  type     = "MX"
  content  = "feedback-smtp.eu-west-1.amazonses.com"
  priority = 10
  ttl      = 1
}
