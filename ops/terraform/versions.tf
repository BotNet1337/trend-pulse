# Terraform + provider version pins (ADR-005 §5). Reproducible: same plugin
# versions locally, in CI and on prod. Bump deliberately, never float.
terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    # DigitalOcean: VPS (droplet), cloud firewall, DNS records.
    # NOTE: vps/dns/firewall.tf are deprecated — real host is Hetzner.
    # These files are left intact (no tfstate; DO resources never applied).
    # Porting to Hetzner server/dns/firewall = separate task (see README).
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.40"
    }

    # Hetzner Object Storage via S3-compatible MinIO provider (TASK-056).
    minio = {
      source  = "aminueza/minio"
      version = "~> 3.0"
    }
  }
}
