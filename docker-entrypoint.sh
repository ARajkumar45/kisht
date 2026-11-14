#!/bin/sh
# Demo config: build the synthetic loan book on first start. A production config makes the
# loan-book tool refuse, so a lost data volume stops the container instead of quietly serving
# made-up borrowers. Then run a kisht command (default: bridge).
# Calls the installed venv directly: `uv run` would re-install the package on every start.
set -e
if [ ! -f data/ledger.sqlite ]; then
  .venv/bin/python tools/make_loan_book.py --config config.docker.yaml
fi
exec .venv/bin/kisht --config config.docker.yaml "$@"
