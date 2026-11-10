import json

from receptionist.tools import TOOL_SCHEMAS, ToolRunner

DETAILS = {"service_id": "haircut-men", "start": "2026-11-10T11:00",
           "customer_name": "Priya", "customer_phone": "9845012345"}


def runner_and_call(guard):
    return ToolRunner(guard), guard.calls.start_call("glow-salon", "en")


def test_model_sees_exactly_two_tools_and_no_confirm_step():
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert names == ["check_availability", "book_visit"]
    book = TOOL_SCHEMAS[1]["function"]["parameters"]
    assert "confirm" not in book["properties"]
    assert set(book["required"]) == {"service_id", "start", "customer_name", "customer_phone"}


def test_check_availability_returns_slots_and_total(guard):
    tools, call = runner_and_call(guard)
    r = tools.run(call, "check_availability", '{"service_id": "haircut-men", "day": "2026-11-10"}')
    assert r.content["ok"] and r.content["slots"][0]["start"] == "2026-11-10T10:00"
    assert r.content["total_free"] == 39 and len(r.content["slots"]) == 6


def test_preferred_time_is_passed_through(guard):
    tools, call = runner_and_call(guard)
    r = tools.run(call, "check_availability",
                  {"service_id": "haircut-men", "day": "2026-11-10", "preferred_time": "12:00"})
    assert any(s["start"].endswith("12:00") for s in r.content["slots"])


def test_refusal_comes_back_as_ok_false_with_a_message(guard):
    tools, call = runner_and_call(guard)
    r = tools.run(call, "check_availability", {"service_id": "massage", "day": "2026-11-10"})
    assert r.content["ok"] is False and r.content["refused"] == "unknown_service"
    assert "Services:" in r.content["message"]


def test_book_visit_only_proposes(guard):
    tools, call = runner_and_call(guard)
    r = tools.run(call, "book_visit", DETAILS)
    assert r.content["status"] == "waiting_for_caller_yes"
    assert "Shall I book it?" in r.content["read_back"]
    assert guard.calls.get(call, "pending_booking")["customer_name"] == "Priya"
    assert guard.bookings.for_staff("glow-salon", "ravi",
                                    *_day_range(guard)) == []          # nothing saved


def test_missing_details_are_asked_for(guard):
    tools, call = runner_and_call(guard)
    r = tools.run(call, "book_visit", {"service_id": "haircut-men"})
    assert r.content["refused"] == "missing_fields"
    assert "customer_name" in r.content["message"]


def test_bad_json_and_unknown_tool_are_errors_and_audited(guard):
    tools, call = runner_and_call(guard)
    bad = tools.run(call, "check_availability", "{not json")
    unknown = tools.run(call, "delete_everything", "{}")
    assert bad.content["refused"] == unknown.content["refused"] == "bad_request"
    assert [e["outcome"] for e in guard.audit.for_call(call)][-2:] == ["error", "error"]


def test_tool_message_format(guard):
    tools, call = runner_and_call(guard)
    msg = tools.run(call, "check_availability",
                    {"service_id": "haircut-men", "day": "2026-11-10"}).as_message("t1")
    assert msg["role"] == "tool" and msg["tool_call_id"] == "t1"
    assert json.loads(msg["content"])["ok"] is True


def _day_range(guard):
    from datetime import datetime
    tz = guard.tz
    return datetime(2026, 11, 10, 0, 0, tzinfo=tz), datetime(2026, 11, 11, 0, 0, tzinfo=tz)
