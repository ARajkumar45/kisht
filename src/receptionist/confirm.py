"""Two word checks done by code, not by the model.

is_clear_yes:   does the caller's reply clearly say yes to the read-back? (D43)
                Strict on purpose: anything unclear counts as "not yes", and the
                agent simply asks again. A wrong "no" costs one question; a wrong
                "yes" costs a wrong booking.
claims_booking: does the agent's reply say something was booked? Used to stop a
                reply that claims a booking when none succeeded.
English, Hindi and Hinglish for now; Kannada words are added with Kannada (D13).
"""
from __future__ import annotations

import re

# Phrases that contain a "no" word but mean yes / no problem.
_HARMLESS = ["no problem", "koi baat nahi", "koi baat nahin", "no worries"]

_NEGATIVE = {
    "no", "nope", "not", "dont", "don't", "cancel", "wait", "hold", "stop", "change",
    "but", "nahi", "nahin", "na", "mat", "ruko", "ruk", "ruka", "lekin", "magar",
    "badlo", "badal", "dusra", "doosra", "nako",
}
_YES_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "correct",
    "right", "fine", "haan", "han", "haa", "ha", "hanji", "ji", "theek", "thik", "bilkul",
    "sahi", "done", "perfect",
}
_YES_PHRASES = ["book it", "go ahead", "please do", "kar do", "kar dijiye", "kar dena",
                "book karo", "book kar"]


# A yes that also names a time, a number or a day is a change request, not a yes:
# "Theek hai, 12 baje kar do" means "ok, make it 12", and must not book 11:00.
_TIME_WORDS = {
    "baje", "am", "pm", "o'clock", "oclock", "subah", "shaam", "sham", "dopahar", "raat",
    "morning", "afternoon", "evening", "night", "noon", "today", "tomorrow", "aaj", "kal",
    "parso", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "somvar", "mangalvar", "budhvar", "guruvar", "shukravar", "shanivar", "ravivar",
    "instead", "rather", "earlier", "later", "pehle", "baad", "jaldi",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def is_clear_yes(text: str) -> bool:
    t = text.lower().strip()
    if not t or t.endswith("?"):
        return False
    for phrase in _HARMLESS:
        t = t.replace(phrase, " ok ")
    if re.search(r"\d", t):
        return False
    words = _words(t)
    if any(w in _NEGATIVE or w in _TIME_WORDS for w in words):
        return False
    return any(w in _YES_WORDS for w in words) or any(p in t for p in _YES_PHRASES)


_CLAIM = re.compile(
    r"\b(booked|i'?ve booked|have booked|is confirmed|are confirmed|confirmed (your|the|for)|"
    r"appointment is set|you'?re all set|book kar (diya|di|diyaa)|book ho (gaya|gayi|gaya hai)|"
    r"booking ho gayi|confirm kar (diya|di)|confirm ho (gaya|gayi))\b")
_NOT_CLAIM = re.compile(r"\b(not|n't|nahi|nahin) (yet )?(been )?(booked|confirmed)\b")


def claims_booking(reply: str) -> bool:
    t = reply.lower()
    return bool(_CLAIM.search(t)) and not _NOT_CLAIM.search(t)


_AVAIL = re.compile(
    r"\b(free|available|availability|khali|khaali|ho sakta (hai|hain)|ho sakti (hai|hain)|"
    r"mil (jayega|jaega|jayegi|jaegi|sakta|sakti)|slots? (hai|hain|is|are)|"
    r"(is|are) (booked|taken|full)|full (hai|hain))\b")
# Note: "is open" is NOT in the list: opening hours come from the config, not the schedule.


def claims_availability(reply: str) -> bool:
    """Does the reply state that some time is free (or not free)?

    Only statements count; questions back to the caller ("which time is good?")
    do not. Used to make sure such statements come from check_availability (D31).
    """
    sentences = re.split(r"(?<=[.!?])\s+", reply.lower().strip())
    return any(_AVAIL.search(s) and not s.endswith("?") for s in sentences)


def safe_reply_instead_of_false_claim(pending: dict | None, language: str) -> str:
    """What the agent says when its reply claimed a booking that did not happen."""
    if pending:
        if language == "hi":
            return f"Book karne se pehle confirm kar loon: {pending['read_back']}"
        return f"Before I book it, let me confirm: {pending['read_back']}"
    if language == "hi":
        return "Abhi tak kuch book nahi hua hai. Aap kaunsi service aur kis time chahte hain?"
    return "Nothing is booked yet. Which service and what time would you like?"
