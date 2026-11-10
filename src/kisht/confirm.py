"""Checks done by code on words, not by the model.

is_clear_yes:    is the borrower's reply a clear yes to the read-back? Strict on purpose: a
                 wrong "no" costs one question, a wrong "yes" saves a promise they did not make.
                 A yes that names a time, a number or a day is a change, not a yes (D71).
claims_*:        does the agent's reply claim something only code can do (a saved promise, a
                 waiver, a received payment)? Used to replace such replies.
leaks_account:   does a reply mention money before identity is verified?
English, Hindi/Hinglish and Devanagari (Sarvam returns Hindi speech in Devanagari, D84).
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


# Devanagari forms: Sarvam speech-to-text returns Hindi speech in Devanagari even in
# en-IN mode, so a caller's "हाँ" or "नहीं" must count the same as "haan" / "nahi".
_YES_DEVANAGARI = {"हाँ", "हां", "हा", "जी", "ठीक", "बिल्कुल", "सही", "हो", "करो", "कर", "दो", "दीजिए"}
_NEGATIVE_DEVANAGARI = {"नहीं", "नही", "ना", "मत", "रुको", "रुकिए", "लेकिन", "मगर", "बदल", "बदलो",
                        "दूसरा", "बाद"}
_TIME_DEVANAGARI = {"बजे", "सुबह", "शाम", "दोपहर", "रात", "कल", "परसों", "आज", "सोमवार", "मंगलवार",
                    "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार", "पहले"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+|[\u0900-\u097f]+", text.lower())


def is_clear_yes(text: str) -> bool:
    t = text.lower().strip()
    if not t or t.endswith("?"):
        return False
    for phrase in _HARMLESS:
        t = t.replace(phrase, " ok ")
    if re.search(r"[\d०-९]", t):
        return False
    words = _words(t)
    if any(w in _NEGATIVE or w in _TIME_WORDS or w in _NEGATIVE_DEVANAGARI
           or w in _TIME_DEVANAGARI for w in words):
        return False
    return (any(w in _YES_WORDS or w in _YES_DEVANAGARI for w in words)
            or any(p in t for p in _YES_PHRASES))



_PROMISE_SAVED = re.compile(
    r"\b(promise (is |has been )?(noted|recorded|saved|registered)|(i'?ve|i have) (noted|recorded"
    r"|saved)|note kar (liya|li)|record kar (liya|diya|di)|darj kar (liya|diya)|"
    r"confirmation (mil gaya|received)|confirm ho gaya)\b")
_WAIVED = re.compile(
    r"\b(waived?|waive kar|maaf kar (diya|denge|dete)|settled?|settlement (is|has been) (done|"
    r"approved)|penalty (is |has been )?(removed|cancelled)|charges? (removed|cancelled)|"
    r"restructured?)\b")
_NOT = re.compile(r"\b(cannot|can't|can not|not able|nahi|nahin|unable)\b")
_PAID = re.compile(r"\b(payment (is |has been )?received|we('ve| have) received your payment|"
                   r"payment mil gay(a|i))\b")


def claims_promise_saved(reply: str) -> bool:
    return bool(_PROMISE_SAVED.search(reply.lower()))


def claims_waiver(reply: str) -> bool:
    """A claim that something was waived/settled. "I can't waive it" is not a claim."""
    for sentence in re.split(r"(?<=[.!?।])\s+", reply.lower()):
        if _WAIVED.search(sentence) and not _NOT.search(sentence):
            return True
    return False


def claims_payment_received(reply: str) -> bool:
    return bool(_PAID.search(reply.lower()))


_STATUS = re.compile(
    r"\b(your|aapka|aapki|aapke|aapko|tumhara|tumhari)\b\W+(?:\w+\W+){0,5}?"
    r"(overdue|outstanding|bakaya|baaki|pending|peeche|late|missed|due|default)\b",
    re.IGNORECASE)


def leaks_account(reply: str, amounts: set[int] | frozenset[int] = frozenset()) -> bool:
    """Before identity is verified: does the reply reveal THIS borrower's money or loan state?
    That is: one of the account's real amounts, or 'your ... overdue / aapka ... baaki' and the
    like. General terms ("2% late fee on overdue amounts", "Rs 500 bounce charge") are allowed."""
    for m in re.finditer(r"\d[\d,]*", reply):
        if int(m.group().replace(",", "")) in amounts:
            return True
    return bool(_STATUS.search(reply))


_LINK_SENT = re.compile(
    r"(link\b.{0,40}\b(sent|bhej (diya|di|rahi|raha|dunga|dungi|deti|deta))|"
    r"(sent|sending|bhej (diya|di|rahi|raha|deti|deta)).{0,40}\blink\b|"
    r"(i'?ll|i will|let me) send (you )?(a |the )?(payment )?link)", re.IGNORECASE)


def claims_link_sent(reply: str) -> bool:
    """Says a payment link was or is being sent. Only send_payment_link can make that true."""
    return bool(_LINK_SENT.search(reply))
