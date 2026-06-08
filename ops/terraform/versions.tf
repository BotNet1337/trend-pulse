# Terraform + provider version pins (ADR-005 §5). Reproducible: same plugin
# versions locally, in CI and on prod. Bump deliberately, never float.
terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    # DigitalOcean: VPS (droplet), cloud firewall, DNS records, object storage
    # (Spaces). A single provider keeps provision (TF) → configure (Ansible)
    # boundary clean; swap to another VPS provider later without touching
    # Ansible. Resources stay schematically correct so `terraform validate` is
    # green offline-ish (init fetches the provider schema once).
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.40"
    }
  }
}
