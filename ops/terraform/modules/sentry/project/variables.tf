variable "organization" {
  description = <<-EOT
    Sentry organization slug (the [org-slug] in sentry.io/organizations/<slug>/).
    Sentry → Settings → General → "Organization Slug".
  EOT
  type        = string
}

variable "team_name" {
  description = "Display name of the team that owns the project"
  type        = string
  default     = "TrendPulse"
}

variable "team_slug" {
  description = "Slug of the team that owns the project"
  type        = string
  default     = "trendpulse"
}

variable "project_name" {
  description = "Display name of the Sentry project"
  type        = string
  default     = "trendpulse-prod"
}

variable "project_slug" {
  description = "Slug of the Sentry project"
  type        = string
  default     = "trendpulse-prod"
}

variable "platform" {
  description = "Sentry platform identifier for the app (e.g. python, node, javascript)"
  type        = string
  default     = "python"
}

variable "resolve_age" {
  description = "Hours after which an unseen issue auto-resolves (0 = never)"
  type        = number
  default     = 720
}

variable "key_name" {
  description = "Name of the client key that carries the DSN"
  type        = string
  default     = "default"
}
