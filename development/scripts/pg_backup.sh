#!/usr/bin/env bash
# development/scripts/pg_backup.sh
#
# Postgres → Hetzner Object Storage backup script.
# Intended to run as a one-shot compose service (pg_backup) inside postgres_net.
#
# Design — two-stage, two-container (see pg-backup.yml):
#   Stage 1 (pg_backup container — pgvector/pgvector image, on postgres_net):
#     pg_dump -Fc → /tmp/pgdump/dump.tmp
#   Stage 2 (backup_uploader container — aws-cli image, with internet egress):
#     aws s3 cp /tmp/pgdump/dump.tmp → s3://$S3_BUCKET/postgres/trendpulse-<ts>.dump
#
# Temp sharing: both containers mount the same named compose volume `pgdump_tmp`
# at /tmp/pgdump.  The aws-cli container runs AFTER pg_dump exits successfully
# (depends_on: condition: service_completed_successfully).  The temp file is
# deleted only after a successful upload (handled in this script or the uploader).
#
# Usage (set by running container stage):
#   STAGE=dump   → runs pg_dump and writes /tmp/pgdump/dump.tmp
#   STAGE=upload → uploads /tmp/pgdump/dump.tmp to S3, then deletes it
#
# Required env:
#   STAGE=dump|upload
#   dump stage:   POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST
#   upload stage: S3_ENDPOINT, S3_REGION, S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
#
# Dump file lands in /tmp/pgdump/dump.tmp during the dump stage.
# The upload stage reads the timestamp written to /tmp/pgdump/dump.ts by the dump
# stage so the S3 key matches the time the dump was taken (not upload time).
#
# Locking (F2): LOCK_FILE is on the shared pgdump_tmp compose volume (DUMP_DIR),
# NOT /tmp.  Both the cron-triggered and manual compose runs share the same named
# volume so flock -n provides real mutual exclusion between concurrent invocations.
# flock -n: fail-fast — a second concurrent run prints a clear message and exits 1.

set -euo pipefail

DUMP_DIR=/tmp/pgdump
LOCK_FILE="${DUMP_DIR}/pgbackup.lock"
DUMP_TMP="${DUMP_DIR}/dump.tmp"
DUMP_TS_FILE="${DUMP_DIR}/dump.ts"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_env() {
  local missing=()
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      missing+=("$var")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    die "Missing required environment variables: ${missing[*]}"
  fi
}

# ---------------------------------------------------------------------------
# Stage dispatch
# ---------------------------------------------------------------------------

STAGE="${STAGE:-}"
if [ -z "$STAGE" ]; then
  die "STAGE env var not set. Use STAGE=dump or STAGE=upload."
fi

# ---------------------------------------------------------------------------
# Stage: dump
# ---------------------------------------------------------------------------

run_dump() {
  require_env POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST

  # mkdir -p BEFORE opening the lock fd — LOCK_FILE lives on the shared volume.
  mkdir -p "${DUMP_DIR}"

  # Acquire lock — prevents parallel cron + manual runs.
  # LOCK_FILE is on the shared pgdump_tmp volume so both containers contend on the
  # same inode.  flock -n: fail fast with a clear message (no silent retry).
  exec 9>"${LOCK_FILE}"
  flock -n 9 || die "Another pg_backup instance is already running (lock: ${LOCK_FILE})."

  # Free-space guard — pg_dump needs at least some headroom.
  # Minimum required: 512 MiB (adjust if DB grows substantially).
  MIN_FREE_KB=524288
  available_kb=$(df -Pk "${DUMP_DIR}" | awk 'NR==2 {print $4}')
  if [ "${available_kb}" -lt "${MIN_FREE_KB}" ]; then
    die "Not enough free space for dump: ${available_kb} KiB available, ${MIN_FREE_KB} KiB required."
  fi

  # Timestamp for the S3 object key — written once here so upload uses the same value.
  TS=$(date -u +%Y%m%d-%H%M%S)
  echo "${TS}" > "${DUMP_TS_FILE}"

  echo "Starting pg_dump (host=${POSTGRES_HOST}, db=${POSTGRES_DB}, user=${POSTGRES_USER}) ..."

  # pg_dump credentials via env — never via CLI args (ps aux would expose them).
  PGPASSWORD="${POSTGRES_PASSWORD}" \
    pg_dump \
      -h "${POSTGRES_HOST}" \
      -U "${POSTGRES_USER}" \
      -d "${POSTGRES_DB}" \
      -Fc \
      -f "${DUMP_TMP}"

  echo "pg_dump complete → ${DUMP_TMP}"
  echo "Timestamp written → ${DUMP_TS_FILE}: ${TS}"

  # Lock released when shell exits (file descriptor closed).
}

# ---------------------------------------------------------------------------
# Stage: upload
# ---------------------------------------------------------------------------

run_upload() {
  require_env S3_ENDPOINT S3_REGION S3_BUCKET AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

  if [ ! -f "${DUMP_TMP}" ]; then
    die "Dump file not found: ${DUMP_TMP}. Did the dump stage complete successfully?"
  fi
  if [ ! -f "${DUMP_TS_FILE}" ]; then
    die "Timestamp file not found: ${DUMP_TS_FILE}. Did the dump stage complete successfully?"
  fi

  TS=$(cat "${DUMP_TS_FILE}")
  S3_KEY="postgres/trendpulse-${TS}.dump"
  S3_URI="s3://${S3_BUCKET}/${S3_KEY}"

  echo "Uploading ${DUMP_TMP} → ${S3_URI} ..."

  # aws cli reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from the environment.
  # Never echo the key values.
  aws s3 cp \
    "${DUMP_TMP}" \
    "${S3_URI}" \
    --endpoint-url "${S3_ENDPOINT}" \
    --region "${S3_REGION}"

  echo "Upload complete: ${S3_URI}"

  # Delete temp file only after successful upload.
  rm -f "${DUMP_TMP}" "${DUMP_TS_FILE}"
  echo "Temp files removed."
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "${STAGE}" in
  dump)   run_dump   ;;
  upload) run_upload ;;
  *)      die "Unknown STAGE='${STAGE}'. Use STAGE=dump or STAGE=upload." ;;
esac
