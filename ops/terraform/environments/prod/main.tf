terraform {
  required_version = ">= 1.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.49"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    minio = {
      source  = "aminueza/minio"
      version = "~> 3.0"
    }
  }
}

provider "hcloud" {
  token = var.hetzner_api_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# MinIO provider for Hetzner Object Storage (S3-compatible)
provider "minio" {
  minio_server   = replace(var.s3_endpoint, "https://", "")
  minio_user     = var.s3_access_key
  minio_password = var.s3_secret_key
  minio_ssl      = true
  minio_region   = var.s3_region
}

# ============================================================
# Hetzner VPS — single host for the Docker stack (nginx edge +
# app + infra). Terraform provisions; Ansible (provision.yml /
# deploy.yml) configures — ADR-005 §5 boundary.
# ============================================================

module "server" {
  source = "../../modules/hetzner/server"

  name        = "trendpulse-prod"
  server_type = var.server_type
  location    = var.location
  image       = "ubuntu-24.04"

  deploy_user     = var.deploy_user
  ssh_key_name    = "trendpulse-deploy"
  ssh_public_keys = [var.ssh_public_key]
  ssh_allowed_ips = var.ssh_allowed_ips

  labels = {
    project     = "trendpulse"
    environment = "production"
  }
}

# ============================================================
# Cloudflare DNS Records → server IP
# proxied=false: certbot (HTTP-01) and direct SSH-by-name need
# the real IP; flip per-record later if CF proxy is wanted.
# ============================================================

module "dns" {
  source = "../../modules/cloudflare/dns-records"

  zone_id   = var.cloudflare_zone_id
  server_ip = module.server.server_ip

  records = {
    root = {
      name    = var.domain
      proxied = false
    }
    app = {
      name    = "app.${var.domain}"
      proxied = false
    }
  }
}

# ============================================================
# Hetzner Object Storage — backup bucket (TASK-056).
# Module instance name `backup_storage` is load-bearing: the
# pre-restructure state was migrated under this address.
# ============================================================

module "backup_storage" {
  source = "../../modules/hetzner/object-storage"

  bucket_name              = var.s3_backup_bucket_name
  backup_expire_after_days = var.backup_expire_after_days
}
