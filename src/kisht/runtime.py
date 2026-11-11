"""Everything a running Kisht process needs, built once from config.yaml: lenders, ledger,
call state, audit log, one policy guard per lender, agreements, the insights store (call log,
traces, reviews, desk) and the model factory. The CLI, the voice bridge, the day simulator and
the dashboard API all start from here, so they cannot drift apart."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kisht.adapters.call_state import RedisCallState
from kisht.audit import AuditLog
from kisht.config import Config, LLMFactory, load_config
from kisht.guard import PolicyGuard
from kisht.insights import InsightsStore
from kisht.knowledge import Agreement
from kisht.ledger import SqliteLedger
from kisht.lender import LenderRegistry
from kisht.tracing import setup_tracing


@dataclass
class Runtime:
    cfg: Config
    lenders: LenderRegistry
    ledger: SqliteLedger
    calls: RedisCallState
    audit: AuditLog
    guards: dict[str, PolicyGuard]
    agreements: dict[str, Agreement]
    insights: InsightsStore
    models: LLMFactory


def build(config: str | Config = "config.yaml", *, audit_name: str = "kisht",
          now: Callable[[], datetime] | None = None, calls: RedisCallState | None = None,
          tracing: bool = True) -> Runtime:
    cfg = load_config(config) if isinstance(config, (str, Path)) else config
    lenders = LenderRegistry.from_dir(cfg.lenders_dir)
    ledger = SqliteLedger(cfg.stores.ledger_db)
    calls = calls or RedisCallState.from_url(cfg.stores.redis_url)
    audit = AuditLog(f"{cfg.stores.audit_dir}/{audit_name}_{datetime.now():%Y%m%d}.jsonl")
    insights = InsightsStore(cfg.stores.insights_db)
    if tracing:
        setup_tracing(insights, cfg.tracing.otlp_endpoint)
    agreements = {}
    for lid in lenders.ids():
        path = Path(cfg.knowledge_dir) / f"{lid}.yaml"
        if path.exists():
            agreements[lid] = Agreement.load(path)
    guards = {lid: PolicyGuard(lenders.get(lid), ledger, calls, audit, now=now)
              for lid in lenders.ids()}
    return Runtime(cfg, lenders, ledger, calls, audit, guards, agreements, insights,
                   LLMFactory(cfg))
