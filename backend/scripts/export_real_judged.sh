#!/usr/bin/env bash
# Read-only export of the per-cluster, in-window aggregates that feed the
# score-meaningfulness eval (TASK-085). One row per SCOREABLE cluster (>= 1 post in
# the 24h window before the cluster's updated_at anchor — same window as
# scorer.tasks._build_score_inputs / TASK-079). Output columns match what the judge
# fills into backend/data/eval/real_judged.sample.csv (label/ordinal added by hand).
#
# This is strictly READ-ONLY (\copy SELECT) — it never mutates the database. No raw
# post text is exported beyond the cluster's own `topic` (the human-readable label
# the judge reads); posts.text is NULL in prod anyway (retention; ADR-002 §4).
#
# Usage (run from a host with read-only SSH to prod):
#   PROD_HOST=deploy@167.233.81.243 SSH_KEY=~/.ssh/id_ed25519 \
#     bash backend/scripts/export_real_judged.sh > /tmp/real_windowed.csv
#
# Then judge each row (label 1=signal / 0=noise, ordinal severity) into
# backend/data/eval/real_judged.sample.csv with channel_avg = views/posts_in_window
# (cold-channel fallback, matches scoring_replay) and watched_channels_count = 10
# (ASSUMED — no live watchlists in the corpus).
set -euo pipefail

PROD_HOST="${PROD_HOST:-deploy@167.233.81.243}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
PG_USER="${PG_USER:-trendpulse}"
PG_DB="${PG_DB:-trendpulse}"

# Single-line query (psql \copy requires it on one line, no SQL comments).
read -r -d '' QUERY <<'SQL' || true
with windowed as (select c.id as cluster_id, c.user_id as user_id, c.topic as topic, c.updated_at as updated_at, p.channel_id as channel_id, p.posted_at as posted_at, p.views as views, p.forwards as forwards, p.reactions as reactions from clusters c join posts p on p.cluster_id = c.id and p.posted_at >= c.updated_at - interval '24 hours' and p.posted_at <= c.updated_at) select cluster_id, user_id, topic, count(*) as posts_in_window, count(distinct channel_id) as unique_channels, sum(views) as views, sum(forwards) as forwards, sum(reactions) as reactions, extract(epoch from (max(posted_at) - min(posted_at))) / 3600.0 as delta_hours from windowed group by cluster_id, user_id, topic, updated_at order by posts_in_window desc, views desc
SQL

ONELINE=$(printf '%s' "$QUERY" | tr '\n' ' ')

ssh -o BatchMode=yes -i "$SSH_KEY" "$PROD_HOST" \
  "C=\$(docker ps -q -f name=trendpulse_postgres); \
   docker exec \$C psql -U ${PG_USER} -d ${PG_DB} -c \"\\copy (${ONELINE}) to stdout with (format csv, header true)\""
