#!/usr/bin/env sh
# One-shot wrapper: QR-login a technical Telegram account and print its
# StringSession. Reads TELEGRAM_API_ID/HASH from sensitive.env (gitignored),
# pulls `qrcode` ephemerally via uv, and runs the QR generator. No code/SMS
# needed — scan the QR with the account's Telegram app
# (Settings -> Devices -> Link Desktop Device).
#
# Usage:  sh development/scripts/get-telegram-session.sh
set -eu

ROOT="/Users/macbookpro16/work/botnet/apps/trendPulse"
ENVF="$ROOT/development/env/sensitive.env"
UV="$HOME/.local/bin/uv"

[ -f "$ENVF" ] || { echo "missing $ENVF (run: make ansible-unpack)"; exit 1; }
[ -x "$UV" ]  || { echo "uv not found at $UV"; exit 1; }

# Extract the two creds WITHOUT sourcing the file (it contains <placeholder>
# values with shell-special chars that would break `.`/source).
TELEGRAM_API_ID="$(grep -E '^TELEGRAM_API_ID='   "$ENVF" | head -1 | cut -d= -f2-)"
TELEGRAM_API_HASH="$(grep -E '^TELEGRAM_API_HASH=' "$ENVF" | head -1 | cut -d= -f2-)"
export TELEGRAM_API_ID TELEGRAM_API_HASH

[ -n "$TELEGRAM_API_ID" ] && [ -n "$TELEGRAM_API_HASH" ] || {
  echo "TELEGRAM_API_ID / TELEGRAM_API_HASH not set in $ENVF"; exit 1; }

echo "Launching QR login (scan with the Telegram app)..."
exec "$UV" run --with qrcode --directory "$ROOT/backend" \
  python "$ROOT/development/scripts/gen_telegram_session_qr.py"
