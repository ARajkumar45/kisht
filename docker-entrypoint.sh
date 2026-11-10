#!/bin/sh
# Build the synthetic loan book on first start, then run a kisht command (default: bridge).
set -e
if [ ! -f data/ledger.sqlite ]; then
  uv run --no-dev python tools/make_loan_book.py --config config.docker.yaml
fi
exec uv run --no-dev kisht --config config.docker.yaml "$@"
