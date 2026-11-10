"""Shared setup for the Kisht tests. Clock fixed: Tuesday 2026-11-10, 10:00 in India."""
from datetime import datetime

import fakeredis
import pytest
from kisht_support import IST, make_account

from kisht.adapters.call_state import RedisCallState
from kisht.audit import AuditLog
from kisht.guard import PolicyGuard
from kisht.ledger import SqliteLedger
from kisht.lender import load_lender


@pytest.fixture
def clock():
    return {"now": datetime(2026, 11, 10, 10, 0, tzinfo=IST)}


@pytest.fixture
def lender():
    return load_lender("lenders/demo-nbfc.yaml")


@pytest.fixture
def ledger():
    return SqliteLedger()


@pytest.fixture
def calls():
    return RedisCallState(fakeredis.FakeRedis(decode_responses=True))


@pytest.fixture
def guard(lender, ledger, calls, clock):
    return PolicyGuard(lender, ledger, calls, AuditLog(), now=lambda: clock["now"])


@pytest.fixture
def account(ledger):
    return make_account(ledger)


@pytest.fixture
def call(guard, calls, account):
    """A chat conversation bound to the overdue account (identity not yet verified)."""
    call_id = calls.start_call("demo-nbfc", "hi")
    guard.start_contact(call_id, borrower_id=account[0], loan_id=account[1], channel="chat")
    return call_id


@pytest.fixture
def verified(guard, call):
    guard.verify_identity(call, date_of_birth="1990-04-02")
    return call
