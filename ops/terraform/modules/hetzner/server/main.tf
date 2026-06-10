terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.49"
    }
  }
}

# ============================================================
# Cloud-init: Docker, UFW, deploy user
# ============================================================

locals {
  cloud_init = templatefile("${path.module}/cloud-init.yml.tftpl", {
    deploy_user     = var.deploy_user
    ssh_public_keys = var.ssh_public_keys
  })
}

# ============================================================
# SSH Key
# ============================================================

resource "hcloud_ssh_key" "deploy" {
  count      = var.ssh_key_name != null ? 1 : 0
  name       = var.ssh_key_name
  public_key = var.ssh_public_keys[0]
}

# ============================================================
# Server
# ============================================================

resource "hcloud_server" "this" {
  name        = var.name
  server_type = var.server_type
  location    = var.location
  image       = var.image

  ssh_keys = var.ssh_key_name != null ? [hcloud_ssh_key.deploy[0].id] : var.existing_ssh_key_ids

  user_data = local.cloud_init

  labels = var.labels

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  lifecycle {
    ignore_changes = [ssh_keys]
  }
}

# ============================================================
# Firewall
# ============================================================

resource "hcloud_firewall" "this" {
  name = "${var.name}-fw"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.ssh_allowed_ips
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
}

resource "hcloud_firewall_attachment" "this" {
  firewall_id = hcloud_firewall.this.id
  server_ids  = [hcloud_server.this.id]
}
