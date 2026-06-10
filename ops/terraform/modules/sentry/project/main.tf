terraform {
  required_providers {
    sentry = {
      source  = "jianyuan/sentry"
      version = "~> 0.15"
    }
  }
}

# ============================================================
# Sentry project + client key (DSN) for TrendPulse (TASK-024).
# The provider talks to Sentry SaaS (sentry.io) using an org
# auth token — that token is the ONLY manual bootstrap secret;
# the project, key and DSN below are all managed in Terraform.
# ============================================================

# Team that owns the project. Created here so the whole tree is
# reproducible; if a team with this slug already exists, import it
# (terraform import) rather than letting apply collide.
resource "sentry_team" "this" {
  organization = var.organization
  name         = var.team_name
  slug         = var.team_slug
}

# The project itself — events from the app SDK land here.
resource "sentry_project" "this" {
  organization = var.organization
  teams        = [sentry_team.this.slug]
  name         = var.project_name
  slug         = var.project_slug
  platform     = var.platform
  resolve_age  = var.resolve_age

  # We provision alert rules separately (or not at all yet); don't
  # let Sentry auto-create a noisy default rule.
  default_rules = false
}

# Client key — exposes the DSN the backend SDK needs.
resource "sentry_key" "this" {
  organization = var.organization
  project      = sentry_project.this.slug
  name         = var.key_name
}
