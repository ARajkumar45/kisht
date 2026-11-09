#!/usr/bin/env bash
# Start the Bolna fork's Twilio webhook server (port 8001) from source, with the two
# public tunnel URLs given as arguments (quick tunnels change on every start).
#   tools/run_twilio_server.sh https://<twilio-tunnel>.trycloudflare.com https://<bolna-tunnel>.trycloudflare.com
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 PUBLIC_TWILIO_URL PUBLIC_BOLNA_URL" >&2; exit 2; }
BOLNA="${BOLNA_DIR:-$HOME/Documents/mac/bolna_project}"
cd "$BOLNA/local_setup/telephony_server"
export PUBLIC_TWILIO_URL="$1" PUBLIC_BOLNA_URL="$2"
exec "$BOLNA/.venv312/bin/uvicorn" twilio_api_server:app --host 127.0.0.1 --port 8001
