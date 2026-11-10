"""Synthetic loan book (seeded, so every run is identical). Fictional people, fake numbers
(+91 90000 xxxxx), real-looking Indian cities and pincodes. Nobody real is ever contacted.

Mix relative to `today`: pre-due (EMI in 0-3 days), early overdue (1-30 days past due),
late overdue (31-60, outside the agent's scope), and current accounts.
"""
from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta

from kisht.ledger import SqliteLedger, add_months

FIRST = ["Priya", "Rahul", "Anjali", "Vikram", "Sunita", "Arjun", "Pooja", "Imran", "Kavya",
         "Rohit", "Neha", "Suresh", "Fatima", "Manoj", "Deepa", "Ajay", "Lakshmi", "Sanjay",
         "Meera", "Ravi", "Asha", "Karan", "Nisha", "Gopal", "Shabnam", "Vinod", "Rekha", "Amit"]
LAST = ["Sharma", "Verma", "Singh", "Yadav", "Gupta", "Khan", "Reddy", "Nair", "Patel", "Kumar",
        "Joshi", "Mishra", "Das", "Rao", "Iyer", "Chauhan", "Ansari", "Pandey", "Shetty"]
# city, pincode prefix, share of Hindi speakers among our borrowers there
CITIES = [("Bengaluru", "5600", 0.3), ("Delhi", "1100", 0.85), ("Lucknow", "2260", 0.95),
          ("Patna", "8000", 0.95), ("Jaipur", "3020", 0.9), ("Mumbai", "4000", 0.55),
          ("Pune", "4110", 0.5), ("Indore", "4520", 0.9)]
PRODUCTS = {"two-wheeler": (2500, 4500, 24), "personal": (5000, 15000, 36),
            "consumer-durable": (1000, 3000, 12)}
SCENARIOS = [("pre_due", 0.35), ("early_overdue", 0.30), ("late_overdue", 0.15), ("current", 0.20)]


def _pick(rng: random.Random, weighted):
    return rng.choices([x for x, _ in weighted], [w for _, w in weighted])[0]


def generate(ledger: SqliteLedger, *, lender_id: str, today: date, n: int = 200,
             seed: int = 7) -> Counter:
    rng = random.Random(seed)
    counts: Counter = Counter()
    for i in range(n):
        city, pin, hindi_share = rng.choice(CITIES)
        bid = ledger.add_borrower(
            lender_id=lender_id, borrower_id=f"br_{i:04d}",
            name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            phone=f"+9190000{i:05d}", language="hi" if rng.random() < hindi_share else "en",
            dob=date(rng.randint(1975, 2002), rng.randint(1, 12), rng.randint(1, 28)),
            pincode=f"{pin}{rng.randint(1, 99):02d}", city=city, dnd=rng.random() < 0.05)
        product = rng.choice(list(PRODUCTS))
        lo, hi, tenure = PRODUCTS[product]
        emi = rng.randrange(lo, hi + 1, 50)
        scenario = _pick(rng, SCENARIOS)
        paid_before = rng.randint(2, 9)
        # The instalment that defines the scenario ("anchor") and how many were paid before it.
        if scenario == "pre_due":
            anchor = today + timedelta(days=rng.randint(0, 3))
        elif scenario == "early_overdue":
            anchor = today - timedelta(days=rng.randint(1, 30))
        elif scenario == "late_overdue":
            anchor = today - timedelta(days=rng.randint(31, 60))
        else:
            anchor = today + timedelta(days=rng.randint(6, 25))
        anchor = anchor.replace(day=min(anchor.day, 28))
        first_due = add_months(anchor, -paid_before)
        lid = ledger.add_loan(lender_id=lender_id, borrower_id=bid, product=product,
                              principal=emi * tenure * 85 // 100, emi=emi, tenure_months=tenure,
                              first_due=first_due, loan_id=f"ln_{i:04d}")
        for inst in ledger.instalments(lid)[:paid_before]:
            due = date.fromisoformat(inst["due_date"])
            late = rng.choice([0, 0, 0, 1, 2, 5])            # most pay on time, some a bit late
            ledger.record_payment(lid, emi, due + timedelta(days=late))
        d = ledger.dues(lid, today)
        actual = ("late_overdue" if d.days_past_due > 30 else
                  "early_overdue" if d.days_past_due > 0 else
                  "pre_due" if d.next_due_date and (d.next_due_date - today).days <= 3 else
                  "current")
        counts[actual] += 1
    return counts
