"""Claim versus action: counting what the model said it did against what it did."""
from kisht import claims


def turn(agent, tools=(), replaced=(), refused=(), promise_saved=False):
    return {"borrower": "x", "agent": agent, "tools": list(tools), "replaced": list(replaced),
            "refused": list(refused), "promise_saved": promise_saved}


def test_a_claim_with_nothing_behind_it_that_went_out_is_found():
    heard = claims.reached_borrower([
        turn("Aapka promise record ho gaya hai."),                       # nothing was saved
        turn("Main aapko payment link bhej rahi hoon."),                 # no tool call
        turn("Ek minute, main check kar rahi hoon."),                    # and then nothing
        turn("Aapka payment 15 November ko ho gaya hai."),               # cannot know that
    ])
    assert [h["kind"] for h in heard] == ["promise", "link", "stall", "waiver_or_payment"]


def test_backed_claims_and_code_lines_are_not_counted():
    assert claims.reached_borrower([
        turn("Dhanyavaad, note kar liya: Rs 3000 on Saturday 14 November.", promise_saved=True),
        turn("Aapka vaada record ho gaya hai."),                         # saved a turn earlier
        turn("Maine payment link bhej diya hai.", tools=["send_payment_link"]),
        turn("Link phir se bhej rahi hoon."),                            # a link was sent before
        turn("Maaf kijiye, main yeh nahi kar paayi.", replaced=["false_promise_claim"]),
        turn("Kripya apni janm tithi bataiye."),
    ]) == []


def test_a_link_sent_without_saying_so_is_the_opposite_failure():
    heard = claims.reached_borrower([turn("Theek hai ji.", tools=["send_payment_link"])])
    assert [h["kind"] for h in heard] == ["silent_link"]


def test_summary_splits_the_pass_rate_by_what_code_had_to_catch():
    convs = [
        {"id": "clean", "language": "hi", "passed": True, "turns": [turn("Ji.")], "retries": {}},
        {"id": "saved-by-retry", "language": "hi", "passed": True,
         "turns": [turn("Link bhej diya.", tools=["send_payment_link"])],
         "retries": {"unbacked_claim_retry": 1}},
        {"id": "saved-by-block", "language": "en", "passed": True,
         "turns": [turn("Sorry, I couldn't sort that out.", replaced=["false_promise_claim"])],
         "retries": {}},
        {"id": "corrupt", "language": "en", "passed": True,
         "turns": [turn("Your promise has been recorded.")], "retries": {}},
        {"id": "failed", "language": "en", "passed": False, "turns": [turn("Hello.")],
         "retries": {"stall_retry": 1}},
    ]
    s = claims.summarise(convs)
    p = s["all"]["pass"]
    assert (p["passed"], p["passed_clean"], p["passed_because_code_caught_it"],
            p["passed_with_false_claim_heard"]) == (4, 1, 2, 1)
    assert p["pass_pct"] == 80.0 and p["strict_pct"] == 60.0
    assert s["all"]["attempts"] == 4 and s["all"]["reached_borrower"] == 1
    assert s["all"]["replaced"] == 1 and s["all"]["fixed_by_asking_again"] == 2
    assert s["hi"]["attempts"] == 1 and s["en"]["by_kind"] == {"promise": 2, "stall": 1}
    assert "| en |" in claims.render("t", s)


def test_published_eval_runs_can_be_measured():
    convs = claims.from_eval_run("results/evals/local-qwen3.5-9b-v2")
    s = claims.summarise(convs)
    assert s["all"]["conversations"] == 160 and set(s) >= {"hi", "en", "all"}
    assert s["all"]["attempts"] > 100            # the weakness is real; code catches most
    assert s["all"]["pass"]["passed_because_code_caught_it"] > 0
