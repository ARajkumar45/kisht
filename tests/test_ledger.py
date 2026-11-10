import threading
from datetime import date

import pytest

from kisht.ledger import LedgerError, PromiseLimit, SqliteLedger, add_months
from kisht.loanbook import generate

TODAY = date(2026, 11, 10)


@pytest.fixture
def ledger():
    return SqliteLedger()


def one_loan(ledger, first_due=date(2026, 8, 5), emi=3000, tenure=12):
    bid = ledger.add_borrower(lender_id="demo-nbfc", name="Priya Sharma", phone="+919000000001",
                              language="hi", dob=date(1990, 4, 2), pincode="560038",
                              city="Bengaluru")
    return ledger.add_loan(lender_id="demo-nbfc", borrower_id=bid, product="two-wheeler",
                           principal=30000, emi=emi, tenure_months=tenure, first_due=first_due)


def test_schedule_is_monthly_on_the_same_day():
    assert add_months(date(2026, 11, 28), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 3, 5), -4) == date(2025, 11, 5)


def test_dues_when_one_emi_is_missed(ledger):
    lid = one_loan(ledger)                                # due 5 Aug, 5 Sep, 5 Oct, 5 Nov ...
    for _ in range(3):
        ledger.record_payment(lid, 3000, date(2026, 10, 5))
    d = ledger.dues(lid, TODAY)
    assert (d.overdue_amount, d.days_past_due) == (3000, 5)      # 5 Nov missed, 5 days ago
    assert d.next_due_date == date(2026, 12, 5) and d.next_due_amount == 3000


def test_part_payment_goes_to_the_oldest_instalment(ledger):
    lid = one_loan(ledger)
    ledger.record_payment(lid, 4000, date(2026, 8, 5))            # 3000 + 1000 of September
    inst = ledger.instalments(lid)
    assert (inst[0]["paid"], inst[1]["paid"], inst[2]["paid"]) == (3000, 1000, 0)
    assert ledger.dues(lid, TODAY).overdue_amount == 2000 + 3000 + 3000


def test_non_positive_payment_is_rejected(ledger):
    with pytest.raises(LedgerError):
        ledger.record_payment(one_loan(ledger), 0, TODAY)


def test_open_promise_limit_holds_under_a_race(ledger):
    lid = one_loan(ledger)
    errors, ok = [], []

    def promise():
        try:
            ok.append(ledger.add_promise(loan_id=lid, amount=3000, promised_date=TODAY,
                                         max_open=1))
        except PromiseLimit as e:
            errors.append(e)
    threads = [threading.Thread(target=promise) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 1 and len(errors) == 15
    assert len(ledger.open_promises(lid)) == 1


def test_payment_keeps_an_open_promise(ledger):
    lid = one_loan(ledger)
    ledger.add_promise(loan_id=lid, amount=3000, promised_date=TODAY, max_open=1)
    ledger.record_payment(lid, 3000, TODAY)
    assert ledger.open_promises(lid) == []


def test_payment_link_is_idempotent(ledger):
    lid = one_loan(ledger)
    a = ledger.create_payment_link(loan_id=lid, amount=3000, idempotency_key="call1:3000")
    b = ledger.create_payment_link(loan_id=lid, amount=3000, idempotency_key="call1:3000")
    assert a["id"] == b["id"] and b["reused"] and len(ledger.payment_links(lid)) == 1


def test_contacts_count_and_notes_are_memory(ledger):
    lid = one_loan(ledger)
    bid = ledger.loan(lid)["borrower_id"]
    c1 = ledger.log_contact(lender_id="demo-nbfc", borrower_id=bid, channel="chat",
                            started_utc="2026-11-08T05:00:00+00:00")
    ledger.close_contact(c1, "promise", "Promised 3000 on 12 Nov; salary late.")
    ledger.log_contact(lender_id="demo-nbfc", borrower_id=bid, channel="voice",
                       started_utc="2026-11-10T05:00:00+00:00")
    assert len(ledger.contacts_since(bid, "2026-11-09T00:00:00+00:00")) == 1
    assert ledger.recent_notes(bid)[0]["note"].startswith("Promised 3000")


def test_due_accounts_cover_pre_due_and_early_overdue_only(ledger):
    counts = generate(ledger, lender_id="demo-nbfc", today=TODAY, n=60, seed=1)
    accounts = ledger.due_accounts("demo-nbfc", TODAY)
    assert accounts and all(a["days_past_due"] <= 30 for a in accounts)
    assert len(accounts) == counts["pre_due"] + counts["early_overdue"]


def test_loan_book_is_reproducible():
    a, b = SqliteLedger(), SqliteLedger()
    assert generate(a, lender_id="x", today=TODAY, n=30, seed=3) == \
        generate(b, lender_id="x", today=TODAY, n=30, seed=3)
    assert a.borrower("br_0007") == b.borrower("br_0007")
    assert a.borrower("br_0007")["phone"].startswith("+9190000")    # clearly fake numbers
