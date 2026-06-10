terraform {
  required_version = ">= 1.5"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# ============================================================
# Cloudflare Zone (foresignal.biz — registrar: GoDaddy)
# After apply: set the nameservers from `terraform output nameservers`
# in GoDaddy → DNS → Nameservers → Change.
# ============================================================

module "zone" {
  source = "../../modules/cloudflare/zone"

  account_id = var.cloudflare_account_id
  domain     = var.domain
}

# ============================================================
# Email Routing (inbound forwarding) + Resend DNS (outbound SMTP).
# Resend records stay off (resend_enabled=false) until SMTP creds
# are provisioned — flip the flag and fill resend_dkim_value then.
# ============================================================

module "email_routing" {
  source = "../../modules/cloudflare/email-routing"

  zone_id = module.zone.zone_id
  domain  = var.domain

  email_routes          = var.email_routes
  catch_all_enabled     = var.email_catch_all_enabled
  catch_all_destination = var.email_catch_all_destination
  dmarc_policy          = var.email_dmarc_policy
  dmarc_rua_email       = var.email_dmarc_rua

  resend_enabled       = var.resend_enabled
  resend_dkim_value    = var.resend_dkim_value
  resend_spf_subdomain = var.resend_spf_subdomain
}
