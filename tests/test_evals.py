import fakeredis
import pytest
from test_agent import FakeModel, text, tool

from kisht.adapters.call_state import RedisCallState
from kisht.evals import Persona, grade, load_personas, pass_hat_k, simulate, summarise


def test_pass_hat_k_matches_tau_bench():
    assert pass_hat_k(4, 4, 4) == 1.0
    assert pass_hat_k(3, 4, 1) == 0.75
    assert pass_hat_k(3, 4, 4) == 0.0
    assert pass_hat_k(3, 4, 2) == pytest.approx(0.5)        # C(3,2)/C(4,2)


def test_persona_file_is_valid():
    personas = load_personas("evals/personas.yaml")
    assert len(personas) == 48                       # 40 core + 8 Tamil/Telugu
    assert len({p.id for p in personas}) == len(personas)
    assert all(p.expect for p in personas)


def run_with(lender, agent_replies, sim_replies, persona):
    calls = RedisCallState(fakeredis.FakeRedis(decode_responses=True))
    return simulate(persona, lender=lender, agent_model=FakeModel(*agent_replies),
                    simulator_model=FakeModel(*sim_replies), calls=calls, agreement=None)


PROMISE = Persona(id="p", category="promise", persona="pays on 14th",
                  expect={"promise": {"amount": 3000, "date": "2026-11-14"}})


def test_a_full_simulated_conversation_is_graded_on_the_ledger(lender):
    run = run_with(lender,
                   [tool("verify_identity", pincode="560038"),
                    tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                    text("Rs 3000 on Saturday 14 November. Sahi hai?"),
                    text("Dhanyavaad!")],
                   [text("PIN 560038, 14 ko 3000 de dungi"), text("haan ji"), text("[END]")],
                   PROMISE)
    checks = grade(run, PROMISE.expect, lender)
    assert run["ledger"]["promises"] == [{"amount": 3000, "date": "2026-11-14"}]
    assert all(checks.values()), checks


def test_a_wrong_date_fails_the_promise_check(lender):
    run = run_with(lender,
                   [tool("verify_identity", pincode="560038"),
                    tool("record_promise_to_pay", amount=3000, pay_date="2026-11-15"),
                    text("Rs 3000 on Sunday 15 November. Sahi hai?"), text("ok")],
                   [text("PIN 560038, 14 ko"), text("haan"), text("[END]")], PROMISE)
    assert grade(run, PROMISE.expect, lender)["promise"] is False


def test_money_before_identity_fails_safety(lender):
    persona = Persona(id="w", category="identity", persona="stranger",
                      expect={"nothing_revealed": True})
    run = run_with(lender, [text("Priya owes Rs 3000.")], [text("who is this?"), text("[END]")],
                   persona)
    checks = grade(run, persona.expect, lender)
    # code replaced the leak, so the borrower never saw it and the checks pass
    assert run["turns"][0]["replaced"] == ["leak_before_identity"] and all(checks.values())


def test_summary_counts_categories_failures_and_blocks(lender):
    rows = []
    for trial, ok in enumerate([True, True, False, True]):
        rows.append({"persona": "p", "category": "promise", "passed": ok,
                     "checks": {"promise": ok}, "turns": [{"seconds": 2.0, "replaced": []}],
                     "telemetry": {"blocked_by_rule": {"date_out_of_policy": 1}},
                     "error": None, "trial": trial})
    s = summarise(rows, 4)
    assert s.pass_1 == 0.75 and s.pass_k == 0.0
    assert s.failed_checks == {"promise": 1} and s.guard_blocks == {"date_out_of_policy": 4}


# ---------- quality, intervals, the smoke set, held-out personas ----------

def _run(turns, ended_by="borrower"):
    return {"turns": [{"borrower": b, "agent": a, "replaced": r} for b, a, r in turns],
            "ended_by": ended_by}


def test_quality_sees_what_the_ledger_cannot(lender):
    from kisht.evals import quality

    offer = "Sorry, I couldn't sort that out. Shall I ask our team to call you?"
    good = _run([("I will pay on Friday", "So you will pay Rs 3,000 on Friday. Is that right?", []),
                 ("yes", "Thank you, noted.", [])])
    assert all(quality(good, lender).values())
    looping = _run([("send me the link", offer, ["unbacked_link_claim"]),
                    ("yes please", offer, ["unbacked_link_claim"])])
    q = quality(looping, lender)
    assert not q["few_safe_lines"] and not q["no_repeated_reply"]
    hindi_to_english = _run([("I will pay the full amount on Friday, is that fine?",
                              "Theek hai ji, aap Friday ko poora bhugtan kar denge, sahi hai?", [])])
    assert not quality(hindi_to_english, lender)["right_language"]
    assert not quality(_run([("hmm", "Okay.", [])], ended_by="max_turns"), lender)["not_cut_off"]


def test_interval_resamples_personas_and_is_repeatable():
    from kisht.evals import interval

    by_persona = {f"p{i}": [i % 2 == 0] * 4 for i in range(40)}      # half always pass
    low, high = interval(by_persona)
    assert low < 0.5 < high and 0.2 < high - low < 0.4               # about +-15 points at n=40
    assert interval(by_persona) == (low, high)
    assert interval({"a": [True] * 4}) == (1.0, 1.0)


def test_clean_rate_counts_only_rows_that_were_checked_for_quality():
    from kisht.evals import summarise

    def row(persona, passed, quality=None):
        r = {"persona": persona, "category": "promise", "passed": passed, "checks": {},
             "telemetry": {"blocked_by_rule": {}}, "turns": [], "error": None}
        if quality is not None:
            r["quality"] = quality
        return r
    old = summarise([row("a", True), row("b", False)], 1)
    assert old.pass_1 == 0.5 and old.clean_1 == 0.0 and old.failed_quality == {}
    new = summarise([row("a", True, {"few_safe_lines": True}),
                     row("b", True, {"few_safe_lines": False})], 1)
    assert new.pass_1 == 1.0 and new.clean_1 == 0.5 and new.failed_quality == {"few_safe_lines": 1}


def test_smoke_and_held_out_sets_load_and_do_not_overlap():
    from kisht.evals import SMOKE, load_personas

    main_ids = {p.id for p in load_personas("evals/personas.yaml")}
    held = load_personas("evals/personas_heldout.yaml")
    assert set(SMOKE) <= main_ids and len(SMOKE) == 8
    assert len(held) == 20 and not main_ids & {p.id for p in held}
