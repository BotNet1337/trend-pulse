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
