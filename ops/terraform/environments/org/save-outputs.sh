#!/usr/bin/env bash
# Save terraform outputs to outputs.json after apply.
# Usage: ./save-outputs.sh

set -euo pipefail

OUTPUT_FILE="outputs.json"

terraform output -json > "$OUTPUT_FILE"

echo "Saved to $OUTPUT_FILE"
echo ""
echo "=== Cloudflare Nameservers (set in GoDaddy) ==="
terraform output -json nameservers | jq -r '.[]'
echo ""
echo "=== Zone ID (paste into ../prod/terraform.tfvars cloudflare_zone_id) ==="
terraform output -raw zone_id
echo ""
