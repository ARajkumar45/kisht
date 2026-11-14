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
                    r"(noted|recorded|saved|registered) (your|the|this) promise|"
                    r"(i am|i'?m) (recording|noting|saving) (your|the|this|it|that))\b"),),
    link_sent=(r"link\b.{0,40}\bsent\b", r"\b(sent|sending)\b.{0,40}\blink\b",
               r"\b(i'?ll|i will|let me) send (you )?(a |the )?(payment )?link"),
    waiver=((r"\b(waived?|settled?|settlement (is|has been) (done|approved)|penalty (is |has been )?"
            r"(removed|cancelled)|charges? (removed|cancelled)|restructured?)\b"),),
    stop_contact=((r"\b(will not|won'?t|shall not|will no longer|not going to) (be )?"
                   r"(contact|call|messag|reach|disturb|bother)"),
                  r"\bno (more|further) (calls|messages|contact)\b",
                  r"\b(removed|taken) you (from|off)\b",
                  r"\byou('ve| have| are) (been )?(removed|opted out|unsubscribed)\b",
                  r"\bstop (contacting|calling|messaging) you\b"),
    handed_over=((r"\b(forwarded|passed|escalated|referred|forwarding|passing|escalating|"
                  r"referring|handing|handed)\b.{0,40}\b(team|desk|officer|colleague|supervisor|"
                  r"manager|department|specialist)\b"),
                 (r"\b(i'?ll|i will|i am|i'm|i have|i've) (forward|pass|escalat|refer|hand)\w*"
                  r".{0,40}\b(team|desk|officer|colleague|supervisor|manager|department)\b"),
                 (r"\b(team|officer|colleague|specialist|someone|supervisor|manager) will "
                  r"(call|contact|reach|get back|be in touch)"),
                 r"\bconnecting you (to|with)\b"),
    terms_cue=((r"\b(late fees?|penalt(y|ies)|bounce charges?|charges?|cibil|credit score|"
                r"foreclos\w*|pre-?pay\w*|prepayment|complain\w*|grievance|interest rate|"
                r"emi date|due date (change|shift))\b"),),
    # Only a clear, lasting request. "Don't call me at work" or "not now" must not match.
    stop_request=(r"\b(stop|quit) (calling|contacting|messaging|texting|phoning) me\b",
                  (r"\b(do not|don'?t|never) (call|contact|message|text|phone) me "
                   r"(again|any ?more|ever)\b"),
                  r"\bno more (calls|messages)\b",
                  r"\b(remove|delete|take) (my|this) number\b",
                  r"\b(unsubscribe|opt(ing)? out)\b"),
    hardship_cue=((r"\b(lost my job|laid off|no job|unemployed|hospital\w*|surgery|medical|"
                   r"passed away|died|death|funeral|accident|business (is )?(closed|shut|down))\b"),),
    negation=(r"\b(cannot|can't|can not|not able|unable)\b",),
    paid=(r"\b(payment (is |has been )?received|we('ve| have) received your payment)\b",),
    action_words=((r"\b(record|note|save|promis|link|send|sent|schedul|follow|call ?back|verif|"
                  r"confirm|waiv|settl|escalat|register|team|opt(ed)? out|paid|received|contact|"
                  r"disturb|bother|remov|unsubscrib|forward|refer|connect|colleague|officer)"),),
    stall=(r"let me (check|see|look)|one moment|please hold|hold on",
           r"\b(i'll|i will|let me) (note|record|save) (it|that|this|your promise)"),
    possessive=F({"your"}),
    status=F({"overdue", "outstanding", "pending", "late", "missed", "due", "default"}),
    greeting="Hello, this is {agent} from {lender}. Am I speaking with {first_name}?",
    say={
        "promise_saved": "Thank you, noted: {read_back}.",
        "read_back": "So you will pay {read_back}. Is that right?",
        "fallback": "Sorry, I'm having a technical problem. Our team will contact you. Thank you.",
        "opted_out": ("Understood. I have recorded that, and we will not call or message you "
                      "again. Thank you."),
        "link_sent": "I have sent a payment link for Rs {amount} to your registered mobile number.",
        "team_will_call": ("I have passed this to our team with your details. Someone will "
                           "call you. Thank you."),
        "stuck": "Sorry, I couldn't sort that out. Shall I ask our team to call you?",
        "recorded": "This call is recorded.",
        "payment_pending": ("Thank you. I cannot see a payment from here; once it reaches us, "
                            "it will show on your account."),
        "promise_ask": "Nothing is saved yet. Which date will you pay, and how much?",
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
