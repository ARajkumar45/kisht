"""A backup model answers when the first cannot, and a server that is down is not asked
again for a while."""
import pytest
from test_config import BASE

from kisht.adapters.llm import FailoverModel
from kisht.config import Config
from kisht.ports import ModelReply, ModelUnavailable


class Down:
    name = "down"

    def __init__(self):
        self.asked = 0

    def complete(self, messages, tools=None, **kw):
        self.asked += 1
        raise ModelUnavailable("connection refused")


class Up:
    name = "up"

    def complete(self, messages, tools=None, **kw):
        return ModelReply(content="hello")


class DiesMidSentence:
    name = "dies"

    def stream(self, messages, tools=None, *, on_text, **kw):
        on_text("Your next EMI ")
        raise ModelUnavailable("stream cut")


def test_the_backup_answers_in_the_same_turn():
    down = Down()
    model = FailoverModel(down, Up())
    assert model.complete([]).content == "hello" and model.switched == 1


def test_after_three_failures_the_first_model_is_left_alone_for_a_while():
    now = [0.0]
    down = Down()
    model = FailoverModel(down, Up(), failures=3, cooldown_s=30, clock=lambda: now[0])
    for _ in range(5):
        model.complete([])
    assert down.asked == 3 and model.open()          # the 4th and 5th did not wait on it
    now[0] = 31.0
    model.complete([])
    assert down.asked == 4                           # tried again after the cool-down


def test_a_reply_already_being_spoken_is_not_started_over_by_the_backup():
    heard = []
    model = FailoverModel(DiesMidSentence(), Up())
    with pytest.raises(ModelUnavailable):
        model.stream([], on_text=heard.append)
    assert heard == ["Your next EMI "] and model.switched == 0


def test_a_backup_must_point_at_a_known_server():
    bad = {**BASE, "llm_roles": {**BASE["llm_roles"], "agent": {
        **BASE["llm_roles"]["agent"], "backup": {"server": "nowhere", "model": "m"}}}}
    with pytest.raises(ValueError, match="backup"):
        Config.model_validate(bad)
