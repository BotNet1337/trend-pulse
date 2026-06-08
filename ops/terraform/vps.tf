# Edge/app VPS. Single droplet hosts the Docker stack (nginx edge + app +
# infra). Ansible (provision.yml/deploy.yml) configures it after Terraform
# creates it — provision (TF) → configure (Ansible) boundary (ADR-005 §5).
resource "digitalocean_droplet" "edge" {
  name     = "${var.project_name}-edge"
  region   = var.region
  size     = var.vps_size
  image    = var.vps_image
  ssh_keys = var.ssh_key_fingerprints

  # Hardening defaults; the droplet publishes no app ports itself — only the
  # cloud firewall (firewall.tf) governs ingress, mirroring network-design.
  monitoring = true
  backups    = false

  tags = ["${var.project_name}", "edge"]
}
