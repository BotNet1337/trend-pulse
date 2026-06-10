variable "name" {
  description = "Server name"
  type        = string
}

variable "server_type" {
  description = "Hetzner server type (e.g., cx22, cx32)"
  type        = string
  default     = "cx22"  # cx22=2vCPU/4GB, cx32=4vCPU/8GB — check: hcloud server-type list
}

variable "location" {
  description = "Hetzner datacenter location (e.g., nbg1, fsn1, hel1)"
  type        = string
  default     = "nbg1"
}

variable "image" {
  description = "OS image"
  type        = string
  default     = "ubuntu-24.04"
}

variable "deploy_user" {
  description = "Username for the deploy user"
  type        = string
  default     = "deploy"
}

variable "ssh_public_keys" {
  description = "List of SSH public keys for the deploy user"
  type        = list(string)
}

variable "ssh_key_name" {
  description = "Name for the SSH key in Hetzner (set null to use existing_ssh_key_ids)"
  type        = string
  default     = null
}

variable "existing_ssh_key_ids" {
  description = "List of existing Hetzner SSH key IDs (used when ssh_key_name is null)"
  type        = list(number)
  default     = []
}

variable "ssh_allowed_ips" {
  description = "CIDR blocks allowed to SSH (default: all)"
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "labels" {
  description = "Labels to attach to the server"
  type        = map(string)
  default     = {}
}
