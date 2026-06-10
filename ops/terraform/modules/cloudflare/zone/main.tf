terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

resource "cloudflare_zone" "this" {
  account = {
    id = var.account_id
  }
  name = var.domain
}
