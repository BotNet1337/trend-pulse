output "server_id" {
  description = "Hetzner server ID"
  value       = hcloud_server.this.id
}

output "server_ip" {
  description = "Public IPv4 address"
  value       = hcloud_server.this.ipv4_address
}

output "server_ipv6" {
  description = "Public IPv6 address"
  value       = hcloud_server.this.ipv6_address
}

output "server_status" {
  description = "Server status"
  value       = hcloud_server.this.status
}

output "deploy_user" {
  description = "Deploy username"
  value       = var.deploy_user
}
