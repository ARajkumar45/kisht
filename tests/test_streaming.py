"""Voice replies are released sentence by sentence while the model is still writing. The
borrower must never hear a sentence that the reply checks would have blocked."""
import json
from types import SimpleNamespace

from test_agent import FakeModel, text, tool
from test_voice_bridge import make, request, sse

from kisht.adapters.llm import OpenAICompatibleModel
from kisht.agent import Agent
from kisht.confirm import claims_promise_saved, is_plain_talk
from kisht.languages import say
from kisht.ports import ModelReply, ToolCall


class StreamModel(FakeModel):
    """Writes each scripted reply word by word, and notes what was already said out loud
    just before it finishes writing."""

    def __init__(self, *replies, heard=None):
        super().__init__(*replies)
        self.heard = heard if heard is not None else []
        self.heard_before_end = []

    def stream(self, messages, tools=None, *, on_text):
        reply = self.complete(messages, tools)
        for word in (reply.content or "").split(" "):
            on_text(word + " ")
        self.heard_before_end.append(list(self.heard))
        return reply


def start(guard, calls, account, model):
    return Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                       loan_id=account[1], channel="voice")[0]


def last_said(calls, agent):
    return [m for m in calls.messages(agent.call_id) if m["role"] == "assistant"][-1]["content"]


def test_first_sentence_is_said_before_the_model_finishes_writing(guard, calls, account):
    heard = []
    model = StreamModel(text("Namaste ji, kaise hain aap. Kripya apni janm tithi bataiye? Shukriya"),
                        heard=heard)
    agent = start(guard, calls, account, model)
    result = agent.handle("haan boliye", on_say=heard.append)
    assert model.heard_before_end[0] == ["Namaste ji, kaise hain aap.",
                                         "Kripya apni janm tithi bataiye?"]
    assert heard[-1] == "Shukriya"
    assert result.reply == "Namaste ji, kaise hain aap. Kripya apni janm tithi bataiye? Shukriya"
    assert last_said(calls, agent) == result.reply and result.first_say_s is not None


def test_a_blocked_sentence_is_never_said_and_the_safe_line_follows(guard, calls, account):
    heard = []
    model = StreamModel(text("Namaste ji, kaise hain aap. Aapka 3000 rupaye overdue hai. "
                             "Kab de sakte hain?"), heard=heard)
    agent = start(guard, calls, account, model)                      # identity not verified
    result = agent.handle("haan", on_say=heard.append)
    assert heard == ["Namaste ji, kaise hain aap.", say("hi", "verify_first")]
    assert result.replaced == ["leak_before_identity"] and "3000" not in result.reply
    assert last_said(calls, agent) == "Namaste ji, kaise hain aap. " + say("hi", "verify_first")


def test_a_reply_blocked_from_its_first_sentence_becomes_the_safe_line(guard, calls, account):
    heard = []
    model = StreamModel(text("Aapka 3000 rupaye overdue hai. Kab de sakte hain?"), heard=heard)
    agent = start(guard, calls, account, model)
    result = agent.handle("haan", on_say=heard.append)
    assert heard == [say("hi", "verify_first")] == [result.reply]
    assert result.replaced == ["leak_before_identity"]


def test_tool_turn_says_one_moment_first_and_keeps_it_out_of_the_transcript(guard, calls, account):
    heard = []
    model = StreamModel(tool("verify_identity", date_of_birth="1990-04-02"),
                        text("Dhanyavaad. Aapki EMI Rs 3000 baaki hai."), heard=heard)
    agent = start(guard, calls, account, model)
    result = agent.handle("2 April 1990", on_say=heard.append)
    assert heard[0] == say("hi", "moment") and "Rs 3000" in heard[-1]
    assert model.heard_before_end[0] == []                   # nothing said before the tool call
    assert result.reply.startswith(say("hi", "moment"))      # the log shows all that was said
    assert say("hi", "moment") not in last_said(calls, agent)


def test_let_me_check_is_held_back_and_the_model_is_asked_again(guard, calls, account):
    heard = []
    model = StreamModel(text("Bilkul ji, zaroor bataungi. Main check kar rahi hoon."),
                        tool("verify_identity", date_of_birth="1990-04-02"),
                        text("Aapki EMI Rs 3000 baaki hai."), heard=heard)
    agent = start(guard, calls, account, model)
    result = agent.handle("meri janm tithi 2 April 1990 hai", on_say=heard.append)
    assert not any("check kar" in h for h in heard)
    assert "Rs 3000" in heard[-1] and result.tool_calls == ["verify_identity"]


def test_a_call_is_prepared_while_it_rings_and_the_bridge_does_not_read_twice(
        guard, calls, account):
    import time

    warmed, warmed_all = [], []

    class Warmable(StreamModel):
        def warm(self, messages, tools=None):
            warmed.append(messages[0]["content"])
            warmed_all.append(messages)                   # instructions + greeting + "."

    model = Warmable(text("Kripya apni janm tithi bataiye."))
    _, client = make(guard, calls, model)
    assert client.post("/prepare", json={"model": "demo-nbfc:br_1"}).json() == {"preparing": True}
    assert client.post("/prepare", json={"model": "demo-nbfc:nobody"}).status_code == 404
    for _ in range(50):
        if warmed:
            break
        time.sleep(0.01)
    assert guard.audit.entries == []               # preparing starts no contact
    client.post("/v1/chat/completions", json=request(["haan"]))
    time.sleep(0.05)
    assert len(warmed) == 1                        # the first turn started no second read
    assert warmed[0] == model.requests[0][0]["content"]   # exactly what the call then uses
    assert calls.messages(calls.r.get("bolna:run:run-1"))[0]["content"] in str(warmed_all[0])


def test_agent_never_offers_a_date_of_birth_or_pin_before_identity(guard, calls, account):
    heard = []
    model = StreamModel(text("Priya ji, kya aapki date of birth 1990-05-15 hai?"), heard=heard)
    agent = start(guard, calls, account, model)
    result = agent.handle("haan boliye", on_say=heard.append)
    assert result.replaced == ["guessed_identity"] and heard == [say("hi", "verify_first")]


def test_bridge_streams_sentences_and_still_answers_404(guard, calls, account):
    model = StreamModel(text("Namaste ji, kaise hain aap. Kripya apni janm tithi bataiye?"))
    _, client = make(guard, calls, model)
    r = client.post("/v1/chat/completions", json=request(["haan"]))
    assert sse(r) == "Namaste ji, kaise hain aap. Kripya apni janm tithi bataiye?"
    assert client.post("/v1/chat/completions",
                       json=request(["hi"], run="run-2", target="demo-nbfc:nobody")).status_code == 404


def test_adapter_stream_hands_over_text_and_collects_tool_calls():
    def chunk(content=None, tool_calls=None, usage=None):
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(
            delta=SimpleNamespace(content=content, tool_calls=tool_calls))])

    def call(index, cid=None, name=None, arguments=None):
        return SimpleNamespace(index=index, id=cid,
                               function=SimpleNamespace(name=name, arguments=arguments))

    chunks = [chunk("Ek "), chunk("second."),
              chunk(tool_calls=[call(0, "c1", "verify_identity", '{"pincode": ')]),
              chunk(tool_calls=[call(0, arguments='"560038"}')]),
              SimpleNamespace(choices=[], usage=SimpleNamespace(
                  prompt_tokens=10, completion_tokens=5,
                  prompt_tokens_details=SimpleNamespace(cached_tokens=8)))]
    model = OpenAICompatibleModel(base_url="http://localhost:1/v1", model="m")
    seen = {}
    model.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: seen.update(kw) or iter(chunks))))
    pieces = []
    reply = model.stream([{"role": "user", "content": "hi"}], on_text=pieces.append)
    assert pieces == ["Ek ", "second."] and reply.content == "Ek second."
    assert [(t.name, json.loads(t.arguments)) for t in reply.tool_calls] == [
        ("verify_identity", {"pincode": "560038"})]
    assert reply.cached_tokens == 8 and seen["stream"] is True


def test_words_written_before_a_tool_call_are_not_said_early(guard, calls, account):
    """Seen live in Tamil: "your promise is recorded" was written just before the tool call
    that refused the promise. Such words are the model's guess; they must wait."""
    guess = "சரி, உங்கள் வாக்குறுதி பதிவு செய்யப்பட்டது. நான் ஒரு அழைப்பைத் திட்டமிடுகிறேன்."
    assert claims_promise_saved(guess) and not is_plain_talk(guess)
    heard = []
    model = StreamModel(tool("verify_identity", date_of_birth="1990-04-02"), text("EMI Rs 3000."),
                        ModelReply(content=guess, tool_calls=[ToolCall(
                            "t1", "record_promise_to_pay",
                            json.dumps({"amount": 3000, "pay_date": "2027-03-01"}))]),
                        text("Maaf kijiye, yeh tareekh nahi ho sakti. Kya 14 November theek hai?"),
                        heard=heard)
    agent = start(guard, calls, account, model)
    agent.handle("2 April 1990", on_say=heard.append)
    heard.clear()
    result = agent.handle("1 March ko de dunga", on_say=heard.append)
    assert result.refused == ["date_out_of_policy"]
    assert heard[0] == say("hi", "moment") and not any("பதிவு" in h for h in heard)
    assert "14 November" in heard[-1]


def test_only_plain_sentences_may_be_said_early():
    for plain in ["Samajh gayi, salary late aana mushkil hota hai.", "I understand, that is hard.",
                  "சரி, புரிகிறது.", "అర్థమైంది, పర్వాలేదు."]:
        assert is_plain_talk(plain), plain
    for not_plain in ["Aapki EMI 5050 rupaye hai.", "Maine note kar liya hai.",
                      "Main link bhej rahi hoon.", "Your promise has been recorded.",
                      "I will send you a link.", "உங்கள் வாக்குறுதி பதிவு செய்யப்பட்டது.",
                      "లింక్ పంపిస్తున్నాను.", "Aapki pehchaan verify ho gayi hai."]:
        assert not is_plain_talk(not_plain), not_plain
    for claim in ["Aapka vaada record ho gaya hai.", "మీ హామీ నమోదు అయింది.",
                  "The system has recorded your promise."]:
        assert claims_promise_saved(claim), claim


def test_a_promise_claim_without_the_tool_gets_one_more_try(guard, calls, account):
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"), text("EMI Rs 3000."),
                      text("Maine aapka payment record kar liya hai."),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("To Rs 3000, 14 November ko. Sahi hai?"))
    agent = start(guard, calls, account, model)
    agent.handle("2 April 1990")
    result = agent.handle("14 ko poora de dunga")
    assert result.tool_calls == ["record_promise_to_pay"] and not result.replaced
    assert "14 November" in result.reply


def test_voice_turn_records_seconds_to_first_words_and_chat_does_not(guard, calls, account):
    from kisht.insights import InsightsStore

    store = InsightsStore()
    model = StreamModel(text("Namaste ji, kaise hain aap. Kripya apni janm tithi bataiye?"),
                        text("Ji."))
    agent = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                        loan_id=account[1], channel="voice", insights=store)[0]
    agent.handle("haan", on_say=lambda piece: None)
    agent.handle("theek hai")                                 # no listener: not a voice turn
    turns = store.turns(agent.call_id)
    assert turns[1]["first_s"] is not None and turns[2]["first_s"] is None
