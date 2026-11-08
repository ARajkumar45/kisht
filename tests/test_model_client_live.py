"""Talks to the real local model. Skipped by default; run with: uv run pytest -m live

Goes through the full CallSession (with its retry), because that is what callers get.
"""
import json
import urllib.request

import pytest

from receptionist.model_client import DEFAULT_BASE_URL, OpenAICompatibleClient
from receptionist.session import CallSession

pytestmark = pytest.mark.live


def _server_up() -> bool:
    try:
        urllib.request.urlopen(DEFAULT_BASE_URL + "/models", timeout=2)
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def model():
    if not _server_up():
        pytest.skip("local model server is not running on port 8080")
    return OpenAICompatibleClient()


@pytest.mark.parametrize("question, day", [
    ("Kal men's haircut ke liye slot hai kya?", "2026-11-10"),
    ("Any manicure slot on Saturday?", "2026-11-14"),
])
def test_slot_question_checks_the_right_day(model, guard, salon, question, day):
    session, _ = CallSession.start(salon, guard.calls, guard, model)
    turn = session.handle(question)
    checked_days = [json.loads(tc["function"]["arguments"]).get("day")
                    for m in guard.calls.messages(session.call_id)
                    for tc in m.get("tool_calls") or []
                    if tc["function"]["name"] == "check_availability"]
    assert day in checked_days, turn.reply
