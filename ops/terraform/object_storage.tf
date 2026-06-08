# Object storage (optional — ADR-005 §5 edge case: don't add a resource for its
# own sake). Off by default; enable when backups/artifacts are actually needed.
# The variable contract is laid down now so enabling later is a one-line flip.
resource "digitalocean_spaces_bucket" "backups" {
  count = var.enable_object_storage ? 1 : 0

  name   = var.object_storage_bucket
  region = var.region
  acl    = "private"
}
