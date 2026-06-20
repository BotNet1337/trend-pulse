terraform {
  required_providers {
    minio = {
      source  = "aminueza/minio"
      version = "~> 3.0"
    }
  }
}

# ============================================================
# S3 Bucket on Hetzner Object Storage (via MinIO provider)
# ============================================================

resource "minio_s3_bucket" "this" {
  bucket = var.bucket_name
  # Teardown (adr-account-autoprovision-verdict): allow `terraform destroy` to delete the
  # bucket even when it still holds backup objects (otherwise destroy blocks on a non-empty
  # bucket). The infra is being decommissioned; backups are intentionally discarded.
  force_destroy = true
}

# Versioning — enables point-in-time restore of backup objects without
# paying for separate write logs.
resource "minio_s3_bucket_versioning" "this" {
  bucket = minio_s3_bucket.this.bucket

  versioning_configuration {
    status = "Enabled"
  }
}

# Lifecycle: expire postgres/ backup objects after backup_expire_after_days.
# TASK-034 writes dumps under postgres/ and relies on this rule for retention
# (no app-level deletion needed).
resource "minio_ilm_policy" "this" {
  bucket = minio_s3_bucket.this.bucket

  rule {
    id         = "expire-backups"
    expiration = "${var.backup_expire_after_days}d"
    filter     = "postgres/"
  }
}
