output "bucket_name" {
  description = "Created bucket name"
  value       = minio_s3_bucket.this.bucket
}
