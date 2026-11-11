#!/bin/sh
# Build the synthetic loan book on first start, then run a kisht command (default: bridge).
# Calls the installed venv directly: `uv run` would re-install the package on every start.
set -e
if [ ! -f data/ledger.sqlite ]; then
  .venv/bin/python tools/make_loan_book.py --config config.docker.yaml
fi
exec .venv/bin/kisht --config config.docker.yaml "$@"
