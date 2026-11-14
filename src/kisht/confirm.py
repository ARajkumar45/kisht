"""Checks done by code on words, not by the model. The words come from the language packs
(kisht/languages), so every check works in each supported language, in Latin letters and in
native script (Sarvam returns Indian-language speech in native script, D84).

is_clear_yes:      is the borrower's reply a clear yes? Strict on purpose: a wrong "no" costs
                   one question, a wrong "yes" saves a promise they did not make. A yes that
                   names a time, a number or a day is a change, not a yes (D71).
is_yes_to_promise: the same, but words that agree with the pending promise are allowed (D88).
claims_*:          does the agent's reply claim something only code can do (a saved promise,
                   a waiver, a received payment, a sent link)? Used to replace such replies.
leaks_account:     does a reply reveal this borrower's money or loan state before identity?
"""
from __future__ import annotations

import re
from datetime import date

from kisht.languages import INDIC, LETTER, PACKS, LanguagePack, word_pattern

_DIGITS = r"0-9०-९௦-௯౦-౯"     # Latin, Devanagari, Tamil, Telugu


def _packs(lang: str | None) -> list[LanguagePack]:
    """English plus the borrower's language; every pack when the language is unknown."""
    if lang is None or lang not in PACKS:
        return list(PACKS.values())
    return [PACKS["en"]] if lang == "en" else [PACKS["en"], PACKS[lang]]


def _words(text: str) -> list[str]:
    return re.findall(rf"[a-z']+|[{INDIC}]+", text.lower())


def _union(packs: list[LanguagePack], attr: str) -> set[str]:
    out: set[str] = set()
    for p in packs:
        out |= getattr(p, attr)
    return out


def _calendar_words(packs: list[LanguagePack]) -> set[str]:
    """Weekday and month names: naming one in a yes makes it a change request."""
    out: set[str] = set()
    for p in packs:
        for names in (*p.weekdays, *p.months):
            out |= names
    return out


_DAY_NUMBER = re.compile(
    rf"\b[{_DIGITS}]{{1,2}}(st|nd|rd|th)\b|\b[{_DIGITS}]{{1,2}} ?(tarikh|taarikh|tareekh)\b",
    re.IGNORECASE)


def names_a_day(text: str) -> bool:
    """The borrower's words name a day: tomorrow, Friday, 14 November, the 15th."""
    packs = list(PACKS.values())
    words = set(_words(text))
    named = _calendar_words(packs) | _union(packs, "tomorrow") | _union(packs, "day_after")
    return bool(words & named) or bool(_DAY_NUMBER.search(text))


def is_clear_yes(text: str, lang: str | None = None) -> bool:
    t = text.lower().strip()
    if not t or t.endswith("?"):
        return False
    packs = _packs(lang)
    for p in packs:
        for phrase in p.harmless:
            t = t.replace(phrase, " ok ")
    if re.search(f"[{_DIGITS}]", t):
        return False
    words = set(_words(t))
    if words & (_union(packs, "no") | _union(packs, "time_words") | _calendar_words(packs)):
        return False
    return (bool(words & _union(packs, "yes"))
            or any(ph in t for p in packs for ph in p.yes_phrases))


def is_yes_to_promise(text: str, amount: int, pay_date: date, today: date,
                      lang: str | None = None) -> bool:
    """A yes to a promise read-back. Borrowers confirm by repeating it ("haan, kal 3000 de
    dungi", "seri, naalaikku 3000 kattaren"), so words that AGREE with the pending promise are
    dropped before the strict check. Any other number, day or time still means a change (D88)."""
    t = text.lower()
    agree_numbers = {str(amount), str(pay_date.day), f"{pay_date.day:02d}", str(pay_date.year)}
    for num in re.findall(r"\d[\d,]*", t):
        if num.replace(",", "") in agree_numbers:
            t = t.replace(num, " ", 1)
    packs = _packs(lang)
    agree: set[str] = set()
    offset = (pay_date - today).days
    for p in packs:
        if p.weekdays:
            agree |= p.weekdays[pay_date.weekday()]
        if p.months:
            agree |= p.months[pay_date.month - 1]
        agree |= {0: p.today, 1: p.tomorrow, 2: p.day_after}.get(offset, frozenset())
        agree |= p.day_parts             # "tomorrow morning" still agrees with "tomorrow"
    pattern = word_pattern(agree)
    if pattern:
        t = pattern.sub(" ", t)
    t = re.sub(rf"₹|(?<!{LETTER})(rs|rupa(ye|ya|yaa)|rupees?|ரூபாய்|రూపాయలు)(?!{LETTER})\.?",
               " ", t)
    return is_clear_yes(t, lang)


# ---------- claims only code can make ----------

def _compile(attr: str) -> list[re.Pattern]:
    return [re.compile(f, re.IGNORECASE) for p in PACKS.values() for f in getattr(p, attr)]


_PROMISE_SAVED = _compile("promise_saved")
_LINK_SENT = _compile("link_sent")
_WAIVED = _compile("waiver")
_NOT = _compile("negation")
_PAID = _compile("paid")
_STALL = _compile("stall") + [re.compile(r"\.\.\.\s*$")]
_ACTION = _compile("action_words")


def is_plain_talk(text: str) -> bool:
    """Nothing in this text can be a claim: no number (amount, date) and no word about an
    action (record, promise, link, send, verify ...) in any language. Only such sentences
    may be said on a voice call before the model has finished its reply, because until then
    code cannot know whether a tool call follows, and words written before a tool call are
    the model's guess about its result. Seen live in Tamil: "your promise is recorded" came
    just before the tool call that refused it."""
    return not re.search(r"\d", text) and not _any(_ACTION, text)


def _any(patterns: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def claims_promise_saved(reply: str) -> bool:
    return _any(_PROMISE_SAVED, reply)


def claims_waiver(reply: str) -> bool:
    """A claim that something was waived/settled. "I can't waive it" is not a claim."""
    for sentence in re.split(r"(?<=[.!?।])\s+", reply):
        if _any(_WAIVED, sentence) and not _any(_NOT, sentence):
            return True
    return False


def claims_payment_received(reply: str) -> bool:
    return _any(_PAID, reply)


def claims_link_sent(reply: str) -> bool:
    """Says a payment link was or is being sent. Only send_payment_link can make that true."""
    return _any(_LINK_SENT, reply)


_STOP_CONTACT = _compile("stop_contact")
_HANDED_OVER = _compile("handed_over")


def claims_handed_over(reply: str) -> bool:
    """Says the case went to a human. Only escalate_to_human can make that true. An offer
    ("shall I ask our team to call you?") is not a claim."""
    return any(_any(_HANDED_OVER, s) for s in re.split(r"(?<=[.!?।])\s+", reply)
               if not s.rstrip().endswith("?"))


_TERMS_CUE = _compile("terms_cue")
_HARDSHIP_CUE = _compile("hardship_cue")


def asks_about_terms(text: str) -> bool:
    """The borrower asks something the loan agreement answers (fees, credit score ...)."""
    return _any(_TERMS_CUE, text)


def mentions_hardship(text: str) -> bool:
    """The borrower speaks of a job loss, illness or a death."""
    return _any(_HARDSHIP_CUE, text)


_STOP_REQUEST = _compile("stop_request")


def asks_to_stop(text: str) -> bool:
    """The borrower plainly asks never to be contacted again."""
    return _any(_STOP_REQUEST, text)


def claims_stop_contact(reply: str) -> bool:
    """Says we will not contact them again. Only opt_out can make that true."""
    return _any(_STOP_CONTACT, reply)


def is_stall(reply: str) -> bool:
    """'Let me check' with no tool call behind it."""
    return _any(_STALL, reply)


# ---------- leaks before identity ----------

_POSSESSIVE = word_pattern(_union(list(PACKS.values()), "possessive"))
_STATUS_WORDS = word_pattern(_union(list(PACKS.values()), "status"))


def _status_leak(reply: str) -> bool:
    """'your ... overdue', 'aapka ... baaki', 'unga ... nilluvai': a possessive word followed
    within six words by a loan-status word."""
    for m in _POSSESSIVE.finditer(reply):
        window = " ".join(reply[m.end():].split()[:6])
        if _STATUS_WORDS.search(window):
            return True
    return False


def leaks_account(reply: str, amounts: set[int] | frozenset[int] = frozenset()) -> bool:
    """Before identity is verified: does the reply reveal THIS borrower's money or loan state?
    That is: one of the account's real amounts, or 'your ... overdue / aapka ... baaki' and the
    like. General terms ("2% late fee on overdue amounts", "Rs 500 bounce charge") are allowed."""
    for m in re.finditer(r"\d[\d,]*", reply):
        if int(m.group().replace(",", "")) in amounts:
            return True
    return _status_leak(reply)
