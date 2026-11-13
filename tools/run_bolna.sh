#!/usr/bin/env bash
# Start the self-hosted Bolna fork from source (no Docker), on port 5001.
# Overrides the Docker-oriented values in bolna_project/local_setup/.env at launch
# (load_dotenv never overwrites variables that are already set).
set -euo pipefail
BOLNA="${BOLNA_DIR:-$HOME/Documents/mac/bolna_project}"
cd "$BOLNA/local_setup"
export REDIS_URL="${BOLNA_REDIS_URL:-redis://localhost:6379/0}"
export BOLNA_TOOL_URL_HOST_ALLOWLIST="localhost,127.0.0.1"
# The bridge checks this as a bearer token when KISHT_BRIDGE_TOKEN is set (set the same value
# for `kisht bridge`); "local" otherwise.
export CUSTOM_LLM_API_KEY="${KISHT_BRIDGE_TOKEN:-local}"
exec "$BOLNA/.venv312/bin/uvicorn" quickstart_server:app --host 127.0.0.1 --port "${BOLNA_PORT:-5001}"
