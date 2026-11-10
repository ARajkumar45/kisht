"""Helpers shared by the Kisht tests (a unique module name: tests/conftest.py also exists)."""
from datetime import date
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 11, 10)


def make_account(ledger, *, overdue=True, emi=3000, dnd=False, borrower_id="br_1",
                 loan_id="ln_1"):
    """overdue=True: the 5 Nov EMI is unpaid (5 days past due). False: next EMI on 12 Nov."""
    ledger.add_borrower(lender_id="demo-nbfc", borrower_id=borrower_id, name="Priya Sharma",
                        phone="+919000000001", language="hi", dob=date(1990, 4, 2),
                        pincode="560038", city="Bengaluru", dnd=dnd)
    first = date(2026, 8, 5) if overdue else date(2026, 8, 12)
    ledger.add_loan(lender_id="demo-nbfc", borrower_id=borrower_id, product="two-wheeler",
                    principal=60000, emi=emi, tenure_months=24, first_due=first, loan_id=loan_id)
    for _ in range(3):                                   # Aug, Sep, Oct paid
        ledger.record_payment(loan_id, emi, first)
    return borrower_id, loan_id
