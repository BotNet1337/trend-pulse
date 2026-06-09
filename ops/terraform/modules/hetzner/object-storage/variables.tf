variable "bucket_name" {
  description = "S3 bucket name"
  type        = string
}

variable "backup_expire_after_days" {
  description = "Days after which postgres/ backup objects are deleted (lifecycle expiration)"
  type        = number
  default     = 30
}
