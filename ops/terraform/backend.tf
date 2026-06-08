# Remote state (ADR-005 §5 — never local .tfstate in git). S3-compatible
# backend (DigitalOcean Spaces). Bucket/endpoint/credentials are NOT in this
# file — they are supplied at `terraform init` time via:
#
#   terraform init \
#     -backend-config="bucket=<spaces-bucket>" \
#     -backend-config="endpoint=https://<region>.digitaloceanspaces.com" \
#     -backend-config="access_key=$SPACES_ACCESS_ID" \
#     -backend-config="secret_key=$SPACES_SECRET_KEY"
#
# For `terraform validate` use `init -backend=false` so the backend is NOT
# initialized and no remote credentials are required (AC2, edge case).
terraform {
  backend "s3" {
    key = "trendpulse/terraform.tfstate"

    # Spaces is S3-compatible but not real AWS — skip AWS-specific validation.
    region                      = "us-east-1"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    # Locking is provided by the backend; DynamoDB-style lock is AWS-only and omitted.
  }
}
