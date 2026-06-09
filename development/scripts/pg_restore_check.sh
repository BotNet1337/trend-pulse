#!/usr/bin/env bash
# development/scripts/pg_restore_check.sh
#
# Restore-check: two-stage, no docker socket, no docker-in-docker.
#
# Stage dispatch via STAGE env var (set by compose services in pg-backup.yml):
#
#   STAGE=fetch  (restore_fetch service — amazon/aws-cli image):
#     List s3://$S3_BUCKET/postgres/, pick latest .dump, download it to
#     /tmp/restore_check/latest.dump on the shared temp volume.
#     Exits non-zero with a clear message if no dumps found.
#
#   STAGE=check  (restore_check service — pgvector/pgvector image):
#     Run a fully INTERNAL, throwaway Postgres instance inside this container
#     (no TCP, no password, local unix-socket trust):
#       initdb → pg_ctl start → createdb → pg_restore → smoke checks → pg_ctl stop
#     Smoke checks:
#       1. alembic_version table is non-empty (has at least one row)
#       2. users table is queryable (SELECT count(*) succeeds)
#     Prints a PASS/FAIL report; exits 0 on PASS, 1 on FAIL.
#     Cleanup (pg_ctl stop + temp dir removal) runs unconditionally via trap.
#
# No connection to the real postgres service.
# NOT on postgres_net — the restore_check container uses the default bridge.
#
# Required env:
#   STAGE=fetch|check
#   fetch stage: S3_ENDPOINT, S3_REGION, S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
#   check stage: (none beyond the shared volume having /tmp/restore_check/latest.dump)
#
# Optional env (check stage):
#   RESTORE_CHECK_DB   — database name for the throwaway PG (default: restore_check)

set -euo pipefail

STAGE="${STAGE:-}"
if [ -z "${STAGE}" ]; then
  echo "ERROR: STAGE env var not set. Use STAGE=fetch or STAGE=check." >&2
  exit 1
fi

DUMP_DIR=/tmp/restore_check
DUMP_FILE="${DUMP_DIR}/latest.dump"

# ---------------------------------------------------------------------------
# Stage: fetch
# ---------------------------------------------------------------------------

run_fetch() {
  : "${S3_ENDPOINT:?Missing S3_ENDPOINT}"
  : "${S3_REGION:?Missing S3_REGION}"
  : "${S3_BUCKET:?Missing S3_BUCKET}"
  : "${AWS_ACCESS_KEY_ID:?Missing AWS_ACCESS_KEY_ID}"
  : "${AWS_SECRET_ACCESS_KEY:?Missing AWS_SECRET_ACCESS_KEY}"

  mkdir -p "${DUMP_DIR}"

  echo "=== Step 1: Listing s3://${S3_BUCKET}/postgres/ ==="

  # List objects, extract filenames, filter .dump, sort newest-first, take first.
  LATEST_KEY=$(
    aws s3 ls "s3://${S3_BUCKET}/postgres/" \
      --endpoint-url "${S3_ENDPOINT}" \
      --region "${S3_REGION}" \
    | awk '{print $NF}' \
    | grep '\.dump$' \
    | sort -r \
    | head -1
  )

  if [ -z "${LATEST_KEY}" ]; then
    echo "ERROR: No dumps found in s3://${S3_BUCKET}/postgres/ — bucket is empty or prefix has no .dump objects." >&2
    exit 1
  fi

  echo "Latest dump key: postgres/${LATEST_KEY}"

  echo "=== Step 2: Downloading dump ==="

  aws s3 cp \
    "s3://${S3_BUCKET}/postgres/${LATEST_KEY}" \
    "${DUMP_FILE}" \
    --endpoint-url "${S3_ENDPOINT}" \
    --region "${S3_REGION}"

  echo "Downloaded → ${DUMP_FILE}"
  echo "fetch stage complete."
}

# ---------------------------------------------------------------------------
# Stage: check
# ---------------------------------------------------------------------------

run_check() {
  RESTORE_CHECK_DB="${RESTORE_CHECK_DB:-restore_check}"

  if [ ! -f "${DUMP_FILE}" ]; then
    echo "ERROR: Dump file not found: ${DUMP_FILE}. Did the fetch stage complete successfully?" >&2
    exit 1
  fi

  # Throwaway Postgres data dir inside the container — fully ephemeral.
  PG_DATA_DIR=/tmp/restore_pg_data
  PG_SOCKET_DIR=/tmp/restore_pg_run

  # Cleanup on exit — stop throwaway PG and remove temp dirs.
  # shellcheck disable=SC2329  # false positive: invoked via `trap cleanup EXIT`
  cleanup() {
    echo "--- Cleanup ---"
    if [ -d "${PG_DATA_DIR}" ]; then
      # pg_ctl stop: ignore errors (may already be stopped if initdb/restore failed).
      pg_ctl -D "${PG_DATA_DIR}" -m fast stop 2>/dev/null || true
    fi
    # Remove only what this stage owns (PG dirs, log).  The shared volume
    # (DUMP_DIR / latest.dump) was written by the fetch stage (running as root
    # in the aws-cli image) — do not attempt to remove it here; it will be
    # cleaned up when the ephemeral restore_tmp compose volume is removed.
    rm -rf "${PG_DATA_DIR}" "${PG_SOCKET_DIR}" /tmp/restore_pg.log
    echo "--- Cleanup done ---"
  }
  trap cleanup EXIT

  echo "=== Step 1: Initialising throwaway Postgres data dir ==="

  mkdir -p "${PG_DATA_DIR}" "${PG_SOCKET_DIR}"

  # initdb as the container's postgres user (we are already running as postgres in pgvector image).
  initdb \
    -D "${PG_DATA_DIR}" \
    --username=postgres \
    --auth-local=trust \
    --auth-host=trust \
    --no-instructions \
    -E UTF8 \
    >/dev/null

  echo "initdb complete."

  echo "=== Step 2: Starting throwaway Postgres ==="

  # pg_ctl start: use a unix socket in PG_SOCKET_DIR, no TCP (port=-1 disables TCP).
  pg_ctl -D "${PG_DATA_DIR}" \
    -o "-k ${PG_SOCKET_DIR} -p 5555" \
    -l /tmp/restore_pg.log \
    start

  echo "Throwaway PG started (socket: ${PG_SOCKET_DIR}, port: 5555)."

  # PSQL shorthand — connects via unix socket, no password needed (trust auth).
  PSQL="psql -h ${PG_SOCKET_DIR} -p 5555 -U postgres"

  echo "=== Step 3: Creating restore target database ==="

  ${PSQL} -d postgres -c "CREATE DATABASE ${RESTORE_CHECK_DB};" >/dev/null
  echo "Database '${RESTORE_CHECK_DB}' created."

  echo "=== Step 4: Enabling pgvector extension ==="

  ${PSQL} -d "${RESTORE_CHECK_DB}" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
  echo "pgvector extension enabled."

  echo "=== Step 5: Running pg_restore ==="

  # --exit-on-error: fail immediately if any object fails to restore (F3).
  # The vector extension is pre-created above (Step 4) so the benign
  # "extension already exists" error that would otherwise fire is avoided.
  # If a genuinely benign error appears in the future (e.g. a collation warning),
  # document it explicitly here and drop --exit-on-error only for that object
  # by adding a --exclude-table / --exclude-schema flag — never by removing -e globally.
  pg_restore \
    -h "${PG_SOCKET_DIR}" \
    -p 5555 \
    -U postgres \
    -d "${RESTORE_CHECK_DB}" \
    --no-owner \
    --no-privileges \
    --exit-on-error \
    -Fc \
    "${DUMP_FILE}"

  echo "pg_restore complete."

  echo "=== Step 6: Smoke checks ==="

  FAIL=0

  # Check 1: alembic_version is non-empty
  ALEMBIC_RESULT=$(
    ${PSQL} -d "${RESTORE_CHECK_DB}" -t \
      -c "SELECT version_num FROM alembic_version LIMIT 1;" \
    2>&1
  )

  if echo "${ALEMBIC_RESULT}" | grep -qE '^[[:space:]]*[0-9a-f]+'; then
    echo "[PASS] alembic_version is present: $(echo "${ALEMBIC_RESULT}" | tr -d '[:space:]')"
  else
    echo "[FAIL] alembic_version is empty or query failed. Output: ${ALEMBIC_RESULT}" >&2
    FAIL=1
  fi

  # Check 2: users table is queryable (count >= 0, no error)
  USERS_COUNT=$(
    ${PSQL} -d "${RESTORE_CHECK_DB}" -t \
      -c "SELECT count(*) FROM users;" \
    2>&1
  )

  if echo "${USERS_COUNT}" | grep -qE '^[[:space:]]*[0-9]+'; then
    echo "[PASS] users table accessible, count = $(echo "${USERS_COUNT}" | tr -d '[:space:]')"
  else
    echo "[FAIL] users table query failed. Output: ${USERS_COUNT}" >&2
    FAIL=1
  fi

  echo ""
  echo "=============================="
  if [ "${FAIL}" -eq 0 ]; then
    echo "  RESTORE-CHECK: PASS"
    echo "=============================="
    exit 0
  else
    echo "  RESTORE-CHECK: FAIL"
    echo "  See [FAIL] lines above for details."
    echo "=============================="
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "${STAGE}" in
  fetch) run_fetch ;;
  check) run_check ;;
  *)     echo "ERROR: Unknown STAGE='${STAGE}'. Use STAGE=fetch or STAGE=check." >&2; exit 1 ;;
esac
