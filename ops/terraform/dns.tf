# DNS — point the app hostname at the edge droplet. The webhook receiver
# (NOWPayments IPN) and app share the same edge (nginx routes by path), so a
# single A record on the app subdomain is enough.
resource "digitalocean_domain" "app" {
  name = var.domain
}

resource "digitalocean_record" "app" {
  domain = digitalocean_domain.app.id
  type   = "A"
  name   = var.app_subdomain
  value  = digitalocean_droplet.edge.ipv4_address
  ttl    = 300
}
