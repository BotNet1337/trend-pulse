#!/usr/bin/env bash
# Save terraform outputs to tf_outputs.json after apply and print the
# Ansible inventory snippet for ops/ansible/inventory/prod.yml.
# Usage: ./save-outputs.sh

set -euo pipefail

OUTPUT_FILE="tf_outputs.json"

terraform output -json > "$OUTPUT_FILE"

SERVER_IP="$(terraform output -raw server_ip)"
DEPLOY_USER="$(terraform output -raw deploy_user)"

echo "Saved to $OUTPUT_FILE"
echo ""
echo "=== Server ==="
echo "IP:   $SERVER_IP"
echo "SSH:  ssh ${DEPLOY_USER}@${SERVER_IP}   (wait ~2min after create for cloud-init)"
echo ""
echo "=== Ansible inventory (ops/ansible/inventory/prod.yml, gitignored) ==="
cat <<EOF
prod:
  hosts:
    trendpulse-prod:
      ansible_host: ${SERVER_IP}
      ansible_user: ${DEPLOY_USER}
      ansible_ssh_private_key_file: ~/.ssh/id_ed25519
EOF
