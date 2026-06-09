# Hetzner Object Storage — backup bucket (ADR-005, TASK-056).
# Provisioned via the minio provider (S3-compatible Hetzner Object Storage).
# Previously: digitalocean_spaces_bucket (removed — DO resources deprecated, see README).
# Bucket is mandatory — no enable_* flag (P8 decision, 2026-06-09).

module "backup_storage" {
  source = "./modules/hetzner/object-storage"

  bucket_name              = var.s3_backup_bucket_name
  backup_expire_after_days = var.backup_expire_after_days
}
