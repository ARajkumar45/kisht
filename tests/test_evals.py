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
    assert len(personas) == 40
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
