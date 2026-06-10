variable "zone_id" {
  description = "Cloudflare zone ID"
  type        = string
}

variable "server_ip" {
  description = "Target IPv4 address for A-records"
  type        = string
}

variable "records" {
  description = "Map of DNS records to create"
  type = map(object({
    name    = string
    ttl     = optional(number, 1)
    proxied = optional(bool, false)
  }))
}
