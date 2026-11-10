from datetime import UTC, datetime, timedelta

import pytest
from kisht_support import IST, make_account

from kisht.guard import MAX_ID_ATTEMPTS, GuardRefused


def refused(code, fn, *args, **kwargs):
    with pytest.raises(GuardRefused) as e:
        fn(*args, **kwargs)
    assert e.value.code == code, e.value.message
    return e.value


# ---------- R1 contact rules ----------

@pytest.mark.parametrize("hour,minute,allowed", [(7, 59, False), (8, 0, True), (18, 59, True),
                                                 (19, 0, False), (22, 30, False)])
def test_contact_window_in_lender_time(guard, account, clock, hour, minute, allowed):
    clock["now"] = datetime(2026, 11, 10, hour, minute, tzinfo=IST)
    if allowed:
        guard.check_contact(account[0], "voice")
    else:
        refused("outside_contact_window", guard.check_contact, account[0], "voice")


def test_window_uses_india_time_even_if_the_clock_is_utc(guard, account, clock):
    clock["now"] = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)          # 14:30 in India
    guard.check_contact(account[0], "voice")
    clock["now"] = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)         # 19:30 in India
    refused("outside_contact_window", guard.check_contact, account[0], "voice")


def test_dnd_blocks_calls_but_not_chat(guard, ledger):
    b, _ = make_account(ledger, dnd=True, borrower_id="br_dnd", loan_id="ln_dnd")
    refused("dnd", guard.check_contact, b, "voice")
    guard.check_contact(b, "chat")


def test_attempt_caps(guard, calls, account, clock):
    for _ in range(2):
        guard.start_contact(calls.start_call("demo-nbfc", "hi"), borrower_id=account[0],
                            loan_id=account[1], channel="chat")
    refused("daily_attempt_cap", guard.check_contact, account[0], "chat")
    for day in range(1, 3):                               # 2 more on each of the next 2 days
        clock["now"] += timedelta(days=1)
        for _ in range(2):
            guard.start_contact(calls.start_call("demo-nbfc", "hi"), borrower_id=account[0],
                                loan_id=account[1], channel="chat")
    clock["now"] += timedelta(days=1)
    refused("weekly_attempt_cap", guard.check_contact, account[0], "chat")


def test_opted_out_borrower_is_never_contacted(guard, call, account):
    guard.opt_out(call)
    refused("opted_out", guard.check_contact, account[0], "chat")


def test_loan_must_belong_to_the_borrower(guard, calls, ledger, account):
    _, other_l = make_account(ledger, borrower_id="br_2", loan_id="ln_2")
    refused("loan_mismatch", guard.start_contact, calls.start_call("demo-nbfc", "hi"),
            borrower_id=account[0], loan_id=other_l, channel="chat")


# ---------- R2 identity ----------

def test_no_account_detail_before_identity(guard, call):
    refused("identity_not_verified", guard.get_dues, call)
    refused("identity_not_verified", guard.propose_promise, call, amount=3000,
            pay_date="2026-11-12")
    refused("identity_not_verified", guard.send_payment_link, call, amount=3000)


@pytest.mark.parametrize("facts", [{"date_of_birth": "1990-04-02"}, {"date_of_birth": "02/04/1990"},
                                   {"pincode": "560 038"}])
def test_identity_by_dob_or_pincode(guard, call, facts):
    assert guard.verify_identity(call, **facts)["verified"]
    assert guard.get_dues(call)["overdue_amount"] == 3000


def test_identity_locks_after_three_misses_and_never_reveals(guard, call):
    for _ in range(MAX_ID_ATTEMPTS):
        e = refused("identity_mismatch", guard.verify_identity, call, pincode="110001")
        assert "560038" not in e.message
    refused("identity_locked", guard.verify_identity, call, date_of_birth="1990-04-02")


# ---------- R3 promises ----------

def test_dues_tell_the_agent_the_limits(guard, verified):
    d = guard.get_dues(verified)
    assert d["days_past_due"] == 5
    assert d["allowed_promise"] == {"min_amount": 750, "max_amount": 6000,
                                    "latest_date": "2026-11-17"}


@pytest.mark.parametrize("amount,day,code", [
    (3000, "2026-11-09", "date_in_past"),
    (3000, "2026-11-18", "date_out_of_policy"),        # overdue: today + 7 is the latest
    (500, "2026-11-12", "amount_out_of_policy"),       # below 25% of 3000
    (9000, "2026-11-12", "amount_out_of_policy"),      # more than is owed
    (3000, "next friday", "bad_date"),
])
def test_promise_limits(guard, verified, amount, day, code):
    refused(code, guard.propose_promise, verified, amount=amount, pay_date=day)


def test_pre_due_promise_may_go_up_to_due_plus_seven(guard, calls, ledger):
    b, l = make_account(ledger, overdue=False, borrower_id="br_p", loan_id="ln_p")
    c = calls.start_call("demo-nbfc", "en")
    guard.start_contact(c, borrower_id=b, loan_id=l, channel="chat")
    guard.verify_identity(c, pincode="560038")
    assert guard.get_dues(c)["allowed_promise"]["latest_date"] == "2026-11-19"   # 12 Nov + 7
    guard.propose_promise(c, amount=3000, pay_date="2026-11-19")


def test_promise_is_saved_only_after_the_borrowers_yes(guard, verified, ledger, account):
    p = guard.propose_promise(verified, amount=3000, pay_date="2026-11-14")
    assert p["read_back"] == "Rs 3000 on Saturday 14 November"
    refused("borrower_not_confirmed", guard.confirm_promise, verified)
    assert ledger.open_promises(account[1]) == []
    guard.mark_borrower_yes(verified)
    assert guard.confirm_promise(verified)["amount"] == 3000
    assert len(ledger.open_promises(account[1])) == 1
    refused("promise_exists", guard.propose_promise, verified, amount=3000, pay_date="2026-11-15")


def test_a_new_proposal_needs_a_new_yes(guard, verified):
    guard.propose_promise(verified, amount=3000, pay_date="2026-11-14")
    guard.mark_borrower_yes(verified)
    guard.propose_promise(verified, amount=1000, pay_date="2026-11-12")    # changed terms
    refused("borrower_not_confirmed", guard.confirm_promise, verified)


# ---------- R4 payment links, follow-ups, R5 escalation ----------

def test_payment_link_limits_and_idempotency(guard, verified, ledger, account):
    refused("amount_out_of_policy", guard.send_payment_link, verified, amount=100)
    a = guard.send_payment_link(verified, amount=3000)
    b = guard.send_payment_link(verified, amount=3000)
    assert b["already_sent"] and a["link_id"] == b["link_id"]
    assert len(ledger.payment_links(account[1])) == 1


def test_followup_window(guard, call):
    refused("bad_followup_date", guard.schedule_followup, call, on_date="2026-11-10", reason="x")
    refused("bad_followup_date", guard.schedule_followup, call, on_date="2026-12-01", reason="x")
    assert guard.schedule_followup(call, on_date="2026-11-15", reason="after promise")


def test_escalation_reasons_and_no_identity_needed(guard, call, ledger, account):
    """A wrong person or a dispute can be escalated without verifying anyone."""
    refused("bad_reason", guard.escalate_to_human, call, reason="discount", summary="x")
    guard.escalate_to_human(call, reason="wrong_person", summary="Says Priya moved away.")
    assert ledger.escalations(account[1])[0]["reason"] == "wrong_person"


# ---------- R6 banned phrases, telemetry ----------

def test_banned_phrases_in_replies(guard, call):
    assert guard.check_reply(call, "Pay today or we will send the POLICE.") == ["police"]
    assert guard.check_reply(call, "Aapka EMI 12 November ko due hai.") == []


def test_every_decision_is_audited_with_its_rule(guard, call):
    for bad in ("110001", "110002"):
        with pytest.raises(GuardRefused):
            guard.verify_identity(call, pincode=bad)
    guard.verify_identity(call, pincode="560038")
    with pytest.raises(GuardRefused):
        guard.propose_promise(call, amount=10, pay_date="2026-11-12")
    t = guard.audit.telemetry()
    assert t["actions"]["verify_identity"] == {"ok": 1, "denied": 2, "error": 0}
    assert t["blocked_by_rule"] == {"identity_mismatch": 2, "amount_out_of_policy": 1}
