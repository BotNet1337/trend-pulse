terraform {
  required_version = ">= 1.5"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    sentry = {
      source  = "jianyuan/sentry"
      version = "~> 0.15"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Sentry SaaS (sentry.io). The token is only exercised when
# sentry_enabled=true; with the default (false) the module below has
# count=0 and makes no API calls, so an empty token never breaks the
# cloudflare-only apply.
provider "sentry" {
  token = var.sentry_auth_token
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

# ============================================================
# Sentry project + DSN (TASK-024 observability).
# Stays off (sentry_enabled=false) until you create an org auth
# token — flip the flag and set sentry_auth_token + organization,
# then `terraform apply` and read `terraform output -raw sentry_dsn`.
# ============================================================

module "sentry" {
  count  = var.sentry_enabled ? 1 : 0
  source = "../../modules/sentry/project"

  organization = var.sentry_organization
  team_name    = var.sentry_team_name
  team_slug    = var.sentry_team_slug
  project_name = var.sentry_project_name
  project_slug = var.sentry_project_slug
  platform     = var.sentry_platform
}
