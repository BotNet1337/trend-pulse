#!/usr/bin/env bash
# Read-only corpus snapshot export for the offline eval harness (TASK-081).
#
# Exports ONLY metrics + centroids from prod Postgres into two local CSVs:
#   - posts.csv    : id, posted_at, channel_id, user_id, cluster_id, views, forwards, reactions
#   - clusters.csv : id, user_id, first_seen, updated_at, topic, embedding (384-d centroid)
#
# NO raw text is exported (posts.text is NULL for all rows anyway — retention
# purged it; ADR-002 §4). This is a strictly READ-ONLY export (\copy SELECT) — it
# never mutates the database.
#
# Usage (run from a host with read-only SSH to prod):
#   PROD_HOST=deploy@167.233.81.243 \
#   SSH_KEY=~/.ssh/id_ed25519 \
#   OUT_DIR=backend/data/eval \
#   bash backend/scripts/export_corpus.sh
#
# Or, if you have a DATABASE_URL to a read replica / snapshot, skip SSH and run the
# two \copy statements below directly with psql "$DATABASE_URL".
set -euo pipefail

PROD_HOST="${PROD_HOST:-deploy@167.233.81.243}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
OUT_DIR="${OUT_DIR:-backend/data/eval}"
PG_USER="${PG_USER:-trendpulse}"
PG_DB="${PG_DB:-trendpulse}"

mkdir -p "$OUT_DIR"

# Resolve the postgres container name on the prod swarm host, then \copy to stdout.
remote_copy() {
  local query="$1"
  ssh -o BatchMode=yes -i "$SSH_KEY" "$PROD_HOST" \
    "C=\$(docker ps -q -f name=trendpulse_postgres); \
     docker exec \$C psql -U ${PG_USER} -d ${PG_DB} -c \"\\copy (${query}) to stdout with (format csv, header true)\""
}

echo "[export_corpus] exporting posts (metrics only) ..."
remote_copy "select id, posted_at, channel_id, user_id, cluster_id, views, forwards, reactions from posts order by id" \
  > "$OUT_DIR/posts.csv"

echo "[export_corpus] exporting clusters (with centroid) ..."
remote_copy "select id, user_id, first_seen, updated_at, topic, embedding from clusters order by id" \
  > "$OUT_DIR/clusters.csv"

echo "[export_corpus] done:"
wc -l "$OUT_DIR/posts.csv" "$OUT_DIR/clusters.csv"
