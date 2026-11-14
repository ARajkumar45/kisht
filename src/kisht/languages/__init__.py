"""Language packs: everything that depends on the borrower's language, in one place.

Each language is one module (en.py, hi.py, ta.py, te.py) defining PACK. Adding a language is
adding one module and one line in _MODULES; no other code changes. A pack holds:
  - what code says itself (greeting, read-back, fallbacks) and the Sarvam speech code
  - the words code uses to judge the borrower (yes / no / time words, in Latin letters and
    in the native script: Sarvam returns Indian-language speech in native script)
  - the phrases code uses to judge the agent (claims only code can make, leaks, stalls)
  - how to spot the language in a message (script, or common romanised words)

Python's \\w and \\b split Indic words at vowel signs, so matching here uses LETTER, which
includes the Indic blocks, instead of \\b.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import import_module

INDIC = "ऀ-ॣ०-෿‌‍"      # Devanagari..Sinhala, no dandas
LETTER = rf"[\w{INDIC}]"


def word_pattern(words: set[str] | frozenset[str]) -> re.Pattern | None:
    """Whole-word match for any of these words or phrases, Indic-safe."""
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<!{LETTER})(?:{alts})(?!{LETTER})", re.IGNORECASE)


@dataclass(frozen=True)
class LanguagePack:
    code: str
    name: str                                  # as the model is told, e.g. "Tamil"
    sarvam: str                                # Sarvam STT/TTS language code
    script: str = ""                           # regex char range of the native script
    markers: frozenset[str] = frozenset()      # romanised words that signal this language
    # judging the borrower
    yes: frozenset[str] = frozenset()
    yes_phrases: tuple[str, ...] = ()
    no: frozenset[str] = frozenset()
    harmless: tuple[str, ...] = ()             # contain a "no" word but mean "no problem"
    time_words: frozenset[str] = frozenset()   # a yes naming one of these is a change request
    day_parts: frozenset[str] = frozenset()    # morning, evening ...: fine in a yes to a date
    today: frozenset[str] = frozenset()
    tomorrow: frozenset[str] = frozenset()
    day_after: frozenset[str] = frozenset()
    weekdays: tuple[frozenset[str], ...] = ()  # Monday .. Sunday
    months: tuple[frozenset[str], ...] = ()    # January .. December
    weekday_names: tuple[str, ...] = ()        # Monday .. Sunday, as code writes them
    month_names: tuple[str, ...] = ()          # January .. December, as code writes them
    # judging the agent (regex fragments; Indic ones must not use \b)
    promise_saved: tuple[str, ...] = ()
    link_sent: tuple[str, ...] = ()
    waiver: tuple[str, ...] = ()
    negation: tuple[str, ...] = ()             # "cannot": turns a waiver sentence into a refusal
    paid: tuple[str, ...] = ()
    stall: tuple[str, ...] = ()
    stop_contact: tuple[str, ...] = ()         # "we will not contact you again"
    handed_over: tuple[str, ...] = ()          # "I have passed this to our team"
    # the borrower plainly asks never to be contacted again: code records it, not the model
    stop_request: tuple[str, ...] = ()
    # reading the borrower (cues for a note to the model; the model still decides)
    terms_cue: tuple[str, ...] = ()            # a question the loan agreement answers
    hardship_cue: tuple[str, ...] = ()         # job loss, illness, a death
    action_words: tuple[str, ...] = ()         # stems: a sentence with one is never said early
    possessive: frozenset[str] = frozenset()   # "your"
    status: frozenset[str] = frozenset()       # "overdue", "baaki" ...
    # what code says
    greeting: str = ""
    say: dict[str, str] = field(default_factory=dict)
    prompt_note: str = ""                      # extra guidance for the model in this language
    voice_note: str = ""                       # extra guidance on a phone call
    simulator_style: str = ""                  # how the eval's simulated borrower writes


_MODULES = ["en", "hi", "ta", "te"]
PACKS: dict[str, LanguagePack] = {
    m: import_module(f"kisht.languages.{m}").PACK for m in _MODULES}


def pack(code: str) -> LanguagePack:
    return PACKS.get(code, PACKS["en"])


def say(code: str, key: str, **kw) -> str:
    line = pack(code).say.get(key) or PACKS["en"].say[key]
    return line.format(**kw)


def date_words(code: str, d) -> str:
    """A date with its weekday, written in the language itself where the pack has the names
    (Tamil, Telugu) and in English otherwise. The model copies this; it must not translate
    or work out a weekday (it turned "Wednesday 11 November" into "Friday, September 11")."""
    p = pack(code)
    if len(p.weekday_names) == 7 and len(p.month_names) == 12:
        return f"{p.weekday_names[d.weekday()]}, {d.day} {p.month_names[d.month - 1]} {d.year}"
    return f"{d:%A} {d.day} {d:%B %Y}"


def detect(text: str, allowed: list[str] | tuple[str, ...]) -> str | None:
    """The language of one message, or None if unclear. Native script wins; then romanised
    marker words (two or more); a longer message with no marker at all is English."""
    candidates = [PACKS[c] for c in allowed if c in PACKS and c != "en"]
    for p in candidates:
        if p.script and re.search(f"[{p.script}]", text):
            return p.code
    words = set(re.findall(r"[a-z]+", text.lower()))
    best, hits = None, 1
    for p in candidates:
        n = len(words & p.markers)
        if n > hits:
            best, hits = p.code, n
    if best:
        return best
    if "en" in allowed and len(words) >= 4 and not any(words & p.markers for p in candidates):
        return "en"
    return None
