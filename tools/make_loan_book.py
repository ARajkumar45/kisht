"""Create the synthetic loan book.  uv run python tools/make_loan_book.py [--today YYYY-MM-DD]"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from kisht.config import load_config
from kisht.ledger import SqliteLedger
from kisht.loanbook import generate


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    p.add_argument("--lender", default="demo-nbfc")
    p.add_argument("-n", type=int, default=200)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--south", type=int, default=40, help="extra Tamil/Telugu-region borrowers")
    p.add_argument("--db", default=None, help="default: stores.ledger_db from the config")
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args()
    cfg = load_config(a.config)
    if cfg.mode != "demo":
        raise SystemExit(f"{a.config} is not `mode: demo`: refusing to build (and overwrite a "
                         "ledger with) made-up borrowers.")
    db = Path(a.db or cfg.stores.ledger_db)
    if db.exists():
        db.unlink()                                  # always rebuilt from the seed
    counts = generate(SqliteLedger(db), lender_id=a.lender, today=a.today, n=a.n, seed=a.seed,
                      south=a.south)
    print(f"{db}: {a.n + a.south} borrowers as of {a.today} -> {dict(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
