# The public DSN is what the SDK uses to ship events — embeddable in
# clients, not a high-value secret. The provider marks the whole `dsn`
# map sensitive (it also carries the secret DSN), so we unwrap just the
# public member with nonsensitive() to keep this output readable and
# allow `terraform output -raw sentry_dsn` when copying it to the vault.
output "dsn" {
  description = "Sentry DSN (public) — set as SENTRY_DSN / vault_sentry_dsn"
  value       = nonsensitive(sentry_key.this.dsn["public"])
}

output "project_slug" {
  description = "Slug of the created Sentry project"
  value       = sentry_project.this.slug
}

output "team_slug" {
  description = "Slug of the team that owns the project"
  value       = sentry_team.this.slug
}
