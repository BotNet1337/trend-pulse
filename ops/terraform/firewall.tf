# Firewall — MIRRORS network-design.md AC7: the ONLY public ingress is 443
# (HTTPS) and 80 (HTTP → redirect to 443 at nginx). SSH (22) is restricted to
# an allowlist (NOT 0.0.0.0/0). Everything else is closed. Postgres/Redis never
# get a rule here (they are compose-internal networks, never published).
resource "digitalocean_firewall" "edge" {
  name        = "${var.project_name}-edge-fw"
  droplet_ids = [digitalocean_droplet.edge.id]

  # --- Ingress: 80 (redirect), 443 (app), 22 (SSH allowlist only) ---
  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol   = "tcp"
    port_range = "22"
    # Least-privilege: only the configured CIDRs may reach SSH.
    source_addresses = var.ssh_allowlist_cidrs
  }

  # --- Egress: allow outbound (package installs, ACME, API calls, DNS) ---
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
