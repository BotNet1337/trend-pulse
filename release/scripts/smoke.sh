#!/usr/bin/env bash
# release/scripts/smoke.sh
#
# Post-deploy smoke test — the LAST gate of `make deploy` (AC4). A non-zero exit
# here fails the whole deploy (and the swarm has already auto-rolled-back any
# unhealthy rolling update via update_config.failure_action: rollback).
#
# Flow (register → login → watchlist create → /ready 200 → /trending 200):
#   1. GET  /ready            → 200 (db + redis ok)
#   2. POST /auth/register    → create a throwaway smoke user (200/201, or 400
#                               "already exists" on a re-run — idempotent-friendly)
#   3. POST /auth/jwt/login   → 200 + session cookie
#   4. POST /watchlists       → 200/201 (authenticated write path)
#   5. GET  /trending         → 200 (public read path)
#
# HOST contract: pass the base origin WITHOUT trailing slash, e.g.
#   HOST=https://foresignal.biz   release/scripts/smoke.sh
#   HOST=http://127.0.0.1         release/scripts/smoke.sh   (bare-IP / tls_enabled=false)
# Routes are reached at ${HOST}/api/... — prod nginx strips the /api prefix so
# the backend sees /ready, /v1/auth/register, etc. (mirrors docs §A3).
#
# Used both locally (`make -C release smoke HOST=…`) and from the deploy playbook.

set -euo pipefail

HOST="${HOST:-http://127.0.0.1}"
# Strip any trailing slash so ${HOST}/api/... never doubles up.
HOST="${HOST%/}"
API="${HOST}/api"

# Unique-enough throwaway identity (timestamp keeps re-runs from colliding hard;
# a duplicate email just yields a 400 which we tolerate on register).
SMOKE_EMAIL="smoke+$(date -u +%Y%m%d%H%M%S)@trendpulse.local"
SMOKE_PASS="smoke-Passw0rd-$(date -u +%s)"

JAR="$(mktemp)"
trap 'rm -f "${JAR}"' EXIT

red()   { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }

fail() {
  red "[SMOKE FAIL] $*"
  exit 1
}

# http_code <method> <url> [curl-args...]  → echoes the numeric status code.
http_code() {
  local method="$1"; shift
  local url="$1"; shift
  curl -k -s -o /dev/null -w "%{http_code}" -X "${method}" "${url}" "$@" || echo "000"
}

echo "=== smoke against ${HOST} ==="

# 1. Readiness — db + redis must be ok.
echo "--- /ready ---"
code="$(http_code GET "${API}/ready")"
[ "${code}" = "200" ] || fail "/ready expected 200, got ${code}"
green "[PASS] /ready 200"

# 2. Register a throwaway user. 200/201 = created; 400 = already exists (re-run).
echo "--- register ---"
code="$(http_code POST "${API}/v1/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${SMOKE_EMAIL}\",\"password\":\"${SMOKE_PASS}\"}")"
case "${code}" in
  200|201) green "[PASS] register ${code}" ;;
  400)     green "[PASS] register 400 (user already exists — re-run tolerated)" ;;
  *)       fail "register expected 200/201/400, got ${code}" ;;
esac

# 3. Login — must set the session cookie.
echo "--- login ---"
code="$(http_code POST "${API}/v1/auth/jwt/login" \
  -c "${JAR}" \
  -d "username=${SMOKE_EMAIL}&password=${SMOKE_PASS}")"
[ "${code}" = "200" ] || fail "login expected 200, got ${code}"
[ -s "${JAR}" ] || fail "login did not set a session cookie"
green "[PASS] login 200 + cookie"

# 4. Authenticated write — create a watchlist.
echo "--- watchlist create ---"
code="$(http_code POST "${API}/v1/watchlists" \
  -b "${JAR}" \
  -H 'Content-Type: application/json' \
  -d '{"topic":"ai","channel":{"handle":"@technews"},"alert_config":{"score_threshold":70,"min_channels":2,"notification_lang":"en"}}')"
case "${code}" in
  200|201) green "[PASS] watchlist create ${code}" ;;
  *)       fail "watchlist create expected 200/201, got ${code}" ;;
esac

# 5. Public read — /trending must answer 200.
echo "--- /trending ---"
code="$(http_code GET "${API}/v1/trending")"
[ "${code}" = "200" ] || fail "/trending expected 200, got ${code}"
green "[PASS] /trending 200"

echo ""
green "=============================="
green "  SMOKE: PASS"
green "=============================="
