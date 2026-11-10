import json

from kisht.tools import TOOL_SCHEMAS, ToolRunner


def names():
    return {t["function"]["name"] for t in TOOL_SCHEMAS}


def test_there_is_no_tool_to_waive_settle_or_confirm():
    assert names() == {"verify_identity", "get_dues", "record_promise_to_pay", "send_payment_link",
                       "schedule_followup", "escalate_to_human", "opt_out"}


def test_no_tool_takes_an_account_id():
    for t in TOOL_SCHEMAS:
        props = t["function"]["parameters"]["properties"]
        assert not any("loan" in p or "borrower" in p or p.endswith("_id") for p in props)


def test_refusals_come_back_as_data_the_model_can_act_on(guard, call):
    r = ToolRunner(guard).run(call, "get_dues", "{}")
    assert not r.ok and r.content["refused"] == "identity_not_verified"
    assert json.loads(r.as_message("t1")["content"])["refused"] == "identity_not_verified"


def test_promise_tool_returns_a_read_back_not_a_saved_promise(guard, verified, ledger, account):
    r = ToolRunner(guard).run(verified, "record_promise_to_pay",
                              '{"amount": 3000, "pay_date": "2026-11-14"}')
    assert r.ok and r.content["status"] == "waiting_for_borrower_yes"
    assert ledger.open_promises(account[1]) == []


def test_bad_json_and_unknown_tools_are_reported(guard, call):
    runner = ToolRunner(guard)
    assert runner.run(call, "get_dues", "{not json").content["refused"] == "bad_request"
    assert runner.run(call, "waive_penalty", "{}").content["refused"] == "bad_request"
    assert runner.run(call, "send_payment_link", '{"amount": "lots"}').content["refused"] == \
        "bad_request"
