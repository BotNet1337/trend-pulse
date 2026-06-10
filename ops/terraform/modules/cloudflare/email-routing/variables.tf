variable "zone_id" {
  description = "Cloudflare zone ID"
  type        = string
}

variable "domain" {
  description = "Domain name (e.g., foresignal.biz)"
  type        = string
}

variable "email_routes" {
  description = "Map of local-part → destination email (e.g., { support = \"user@gmail.com\" })"
  type        = map(string)
  default     = {}
}

variable "catch_all_enabled" {
  description = "Enable catch-all forwarding"
  type        = bool
  default     = true
}

variable "catch_all_destination" {
  description = "Destination email for catch-all rule"
  type        = string
}

variable "dmarc_policy" {
  description = "DMARC policy: none, quarantine, or reject"
  type        = string
  default     = "none"
}

variable "dmarc_rua_email" {
  description = "Email to receive DMARC aggregate reports (empty = no rua tag)"
  type        = string
  default     = ""
}

# --- Resend SMTP sending ---

variable "resend_enabled" {
  description = "Enable Resend domain verification DNS records (DKIM, SPF, MX for send subdomain)"
  type        = bool
  default     = false
}

variable "resend_dkim_value" {
  description = <<-EOT
    DKIM TXT record value from Resend domain verification page.
    Name is always: resend._domainkey
    Get from: Resend → Domains → Add Domain → DNS Records
  EOT
  type    = string
  default = ""
}

variable "resend_spf_subdomain" {
  description = "Subdomain for Resend SPF/MX (default: send)"
  type        = string
  default     = "send"
}
