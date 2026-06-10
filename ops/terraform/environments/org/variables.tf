variable "cloudflare_api_token" {
  description = <<-EOT
    Cloudflare API token.
    Create at: https://dash.cloudflare.com/profile/api-tokens → Create Token → Custom Token

    Required permissions:
      Account : Account Settings        : Read
      Zone    : Zone                    : Edit
      Zone    : DNS                     : Edit
      Zone    : Email Routing Rules     : Edit

    Zone Resources: Include → All zones (the zone does not exist yet at token-creation time)
  EOT
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID (Dashboard → any site → right sidebar, or Account Home URL)"
  type        = string
}

variable "domain" {
  description = "Primary domain managed in Cloudflare"
  type        = string
  default     = "foresignal.biz"
}

# --- Email Routing ---

variable "email_routes" {
  description = "Map of local-part to destination email (e.g., { support = \"me@gmail.com\" })"
  type        = map(string)
  default     = {}
}

variable "email_catch_all_enabled" {
  description = "Enable catch-all email forwarding"
  type        = bool
  default     = true
}

variable "email_catch_all_destination" {
  description = "Destination email for catch-all rule"
  type        = string
}

variable "email_dmarc_policy" {
  description = "DMARC policy: none, quarantine, or reject"
  type        = string
  default     = "none"
}

variable "email_dmarc_rua" {
  description = "Email for DMARC aggregate reports"
  type        = string
}

# --- Resend SMTP (outbound prod email — verify/reset/renewal letters) ---

variable "resend_enabled" {
  description = "Enable Resend domain verification DNS records (flip to true once SMTP is set up)"
  type        = bool
  default     = false
}

variable "resend_dkim_value" {
  description = "DKIM TXT record value from Resend (the p=... key from Resend → Domains → DNS Records)"
  type        = string
  default     = ""
}

variable "resend_spf_subdomain" {
  description = "Subdomain for Resend SPF/MX (default: send)"
  type        = string
  default     = "send"
}

# --- Sentry SaaS (observability — TASK-024) ---

variable "sentry_enabled" {
  description = "Create the Sentry project + DSN (flip to true once you have an org auth token)"
  type        = bool
  default     = false
}

variable "sentry_auth_token" {
  description = <<-EOT
    Sentry organization auth token (the only manual Sentry secret).
    Create at: Sentry → Settings → Auth Tokens → Create New Token
    Scopes: project:read, project:write, project:admin, team:read, team:write, org:read
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "sentry_organization" {
  description = "Sentry organization slug (Settings → General → Organization Slug)"
  type        = string
  default     = ""
}

variable "sentry_team_name" {
  description = "Display name of the Sentry team that owns the project"
  type        = string
  default     = "TrendPulse"
}

variable "sentry_team_slug" {
  description = "Slug of the Sentry team that owns the project"
  type        = string
  default     = "trendpulse"
}

variable "sentry_project_name" {
  description = "Display name of the Sentry project"
  type        = string
  default     = "trendpulse-prod"
}

variable "sentry_project_slug" {
  description = "Slug of the Sentry project"
  type        = string
  default     = "trendpulse-prod"
}

variable "sentry_platform" {
  description = "Sentry platform identifier for the app (e.g. python, node)"
  type        = string
  default     = "python"
}
