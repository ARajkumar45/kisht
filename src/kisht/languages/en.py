from kisht.languages import LanguagePack

F = frozenset
PACK = LanguagePack(
    code="en", name="English", sarvam="en-IN",
    yes=F({"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "correct",
           "right", "fine", "done", "perfect"}),
    yes_phrases=("go ahead", "please do"),
    no=F({"no", "nope", "not", "dont", "don't", "cancel", "wait", "hold", "stop", "change",
          "but"}),
    harmless=("no problem", "no worries"),
    time_words=F({"am", "pm", "o'clock", "oclock", "morning", "afternoon", "evening", "night",
                  "noon", "today", "tomorrow", "instead", "rather", "earlier", "later"}),
    day_parts=F({"morning", "afternoon", "evening", "night", "noon"}),
    today=F({"today"}), tomorrow=F({"tomorrow"}), day_after=F(),
    weekdays=tuple(F({d}) for d in ["monday", "tuesday", "wednesday", "thursday", "friday",
                                    "saturday", "sunday"]),
    months=tuple(F({m, m[:3]}) for m in [
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december"]),
    promise_saved=((r"\b(promise (is |has been )?(noted|recorded|saved|registered)|(i'?ve|i have) "
                   r"(noted|recorded|saved)|confirmation received|"
                    r"(noted|recorded|saved|registered) (your|the|this) promise)\b"),),
    link_sent=(r"link\b.{0,40}\bsent\b", r"\b(sent|sending)\b.{0,40}\blink\b",
               r"\b(i'?ll|i will|let me) send (you )?(a |the )?(payment )?link"),
    waiver=((r"\b(waived?|settled?|settlement (is|has been) (done|approved)|penalty (is |has been )?"
            r"(removed|cancelled)|charges? (removed|cancelled)|restructured?)\b"),),
    negation=(r"\b(cannot|can't|can not|not able|unable)\b",),
    paid=(r"\b(payment (is |has been )?received|we('ve| have) received your payment)\b",),
    action_words=((r"\b(record|note|save|promis|link|send|sent|schedul|follow|call ?back|verif|"
                  r"confirm|waiv|settl|escalat|register|team|opt(ed)? out|paid|received)"),),
    stall=(r"let me (check|see|look)|one moment|please hold|hold on",
           r"\b(i'll|i will|let me) (note|record|save) (it|that|this|your promise)"),
    possessive=F({"your"}),
    status=F({"overdue", "outstanding", "pending", "late", "missed", "due", "default"}),
    greeting="Hello, this is {agent} from {lender}. Am I speaking with {first_name}?",
    say={
        "promise_saved": "Thank you, noted: {read_back}.",
        "read_back": "So you will pay {read_back}. Is that right?",
        "fallback": "Sorry, I'm having a technical problem. Our team will contact you. Thank you.",
        "stuck": "Sorry, I couldn't sort that out. Shall I ask our team to call you?",
        "moment": "One moment, please.",
        "handover": "I'm connecting you with a colleague from our team, who will take it "
                    "from here. Thank you.",
        "verify_first": "Before I can discuss any details, may I have your date of birth or PIN "
                        "code?",
        "cannot_decide": "I can't decide that myself, but I can pass it to our team with your "
                         "details. Shall I do that?",
        "polite": "I'm sorry if that came out wrong. I'm here to help you find a way that works "
                  "for you.",
        "not_now": "Sorry, we cannot discuss this right now. Thank you, goodbye.",
    },
    simulator_style="simple Indian English.",
)
