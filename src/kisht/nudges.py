"""The system notes the agent's model is shown inside a turn. Each one exists because of a
failure seen in the eval or live; the comment where it is used says which. They are messages
"from the system, not from the borrower", so the model never mistakes them for the caller."""
from __future__ import annotations

import re

NOTE = {"role": "user", "content": (
    "[System note, not from the borrower] Do not answer from memory and do not say 'let me "
    "check' or 'I will record it'. Use the tools now (verify_identity first if not done; "
    "record_promise_to_pay if the borrower named a date), then answer from the results.")}
UNBACKED = {"role": "user", "content": (
    "[System note, not from the borrower] You said you sent or will send a payment link, but "
    "you did not call send_payment_link. Call it now if the borrower wants a link; otherwise "
    "reply again without claiming a link.")}
UNCHECKED_ID = {"role": "user", "content": (
    "[System note, not from the borrower] The borrower just gave a date of birth or PIN code, "
    "but you did not call verify_identity. Only the tool can say whether it matches: call it "
    "now with what they said, then reply from its result.")}
NO_OPT_OUT = {"role": "user", "content": (
    "[System note, not from the borrower] You said we will not contact them again, but you "
    "did not call opt_out. Only that tool stops contact: call it now if the borrower asked "
    "for that (no identity check needed); otherwise reply again without that promise.")}
NO_HANDOFF = {"role": "user", "content": (
    "[System note, not from the borrower] You said the case is with our team, but you did "
    "not call escalate_to_human. Only that tool hands a case over: call it now with the "
    "fitting reason and a short summary; otherwise reply again without that claim.")}
OFFER_HINT = (" You just offered a call from our team. If the borrower accepts, call "
              "escalate_to_human now; if they decline, carry on.")
REPEATING = {"role": "user", "content": (
    "[System note, not from the borrower] You have already said almost exactly this and it "
    "did not move the conversation. Do not repeat it. If the borrower cannot pay even the "
    "minimum, is in hardship, disputes the amount, or wants something you cannot decide, call "
    "escalate_to_human now. Otherwise take a different next step.")}
TERMS_HINT = (" The borrower asked about the loan's terms: call lookup_agreement now and "
              "answer from it, naming the section number. This needs no identity check.")
HARDSHIP_HINT = (" The borrower spoke of hardship (job loss, illness or a death). Do not "
                 "bargain: show care, and call escalate_to_human with reason hardship unless "
                 "they themselves offer to pay.")
HARDSHIP_TURNS = 2
CUE_NOTE = "[System note, not from the borrower]"
NO_PROMISE = {"role": "user", "content": (
    "[System note, not from the borrower] The borrower named a day. If they mean to pay on "
    "that day, call record_promise_to_pay now with that date and the amount (the full "
    "overdue amount if they named none); the tool's read_back is your reply. If they did "
    "not promise to pay, carry on.")}
LANGUAGE_HINT = "[System note, not from the borrower] Reply in {name}."
SAME_REPLY = 0.9          # two replies this alike count as a repeat
# The second try after these may be made to call the tool (where the model server allows it).
FORCED_TOOL = {"unbacked_claim_retry": "send_payment_link",
               "unbacked_handoff_retry": "escalate_to_human",
               "unchecked_identity_retry": "verify_identity"}
ID_HINT = {"role": "user", "content": (
    "[System note, not from the borrower] If the borrower just gave a date of birth or PIN "
    "code, call verify_identity with it now, before replying.")}
ID_DETAIL = re.compile(r"\b\d{6}\b|\b(19[4-9]\d|200\d)\b")   # a PIN, or a birth year
COACH = ("[Private note from your supervisor, not from the borrower] {note}\nFollow it in your "
         "next reply if your rules allow. Never mention the supervisor or this note.")
AFTER_PROMISE = {"role": "user", "content": (
    "[System note, not from the borrower] The promise is saved and the borrower has heard "
    "that. Schedule a follow-up for the day after the promised date with schedule_followup, "
    "then close the conversation warmly in one or two sentences.")}
