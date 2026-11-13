"""Tamil and Telugu get the same code-side checks as Hindi and English, in Latin letters
(chat) and in native script (Sarvam speech-to-text)."""
from datetime import date

import pytest

from kisht.confirm import (
    claims_link_sent,
    claims_payment_received,
    claims_promise_saved,
    claims_waiver,
    is_clear_yes,
    is_stall,
    is_yes_to_promise,
    leaks_account,
)
from kisht.languages import PACKS, detect, say
from kisht.prompt import GREETING

TODAY, PAY = date(2026, 11, 10), date(2026, 11, 11)     # promise for tomorrow, a Wednesday
ALL = ["en", "hi", "ta", "te"]


def test_every_pack_has_every_line_code_speaks():
    for code, p in PACKS.items():
        assert set(p.say) == set(PACKS["en"].say), code
        assert p.greeting and "{first_name}" in p.greeting, code
        assert len(p.weekdays) == 7, code
    assert GREETING["ta"].startswith("வணக்கம்") and GREETING["te"].startswith("నమస్కారం")


@pytest.mark.parametrize("text,lang", [
    ("Seri, naalaikku kattaren, enna problem illa", "ta"),
    ("ஆமாம், நாளைக்கு கட்டுகிறேன்", "ta"),
    ("Sare andi, repu kadatanu, ippudu salary raledu", "te"),
    ("అవును, రేపు కడతాను", "te"),
    ("Haan ji, kal kar dungi", "hi"),
    ("I will pay the full amount on Friday", "en"),
])
def test_language_is_detected(text, lang):
    assert detect(text, ALL) == lang


def test_a_language_the_lender_does_not_allow_is_not_chosen():
    assert detect("ஆமாம், நாளைக்கு கட்டுகிறேன்", ["en", "hi"]) is None


@pytest.mark.parametrize("text,lang", [
    ("seri", "ta"), ("aamaa", "ta"), ("சரி", "ta"), ("ஆமாம்", "ta"), ("paravaillai, seri", "ta"),
    ("sare", "te"), ("avunu", "te"), ("సరే", "te"), ("అవును అలాగే", "te"),
])
def test_yes(text, lang):
    assert is_clear_yes(text, lang)


@pytest.mark.parametrize("text,lang", [
    ("illa", "ta"), ("vendam", "ta"), ("இல்லை", "ta"), ("seri aana naalaikku", "ta"),
    ("ledu", "te"), ("vaddu", "te"), ("లేదు", "te"), ("sare kaani repu", "te"),
    ("seri?", "ta"),
])
def test_no_or_change(text, lang):
    assert not is_clear_yes(text, lang)


@pytest.mark.parametrize("text,lang", [
    ("Seri, naalaikku 3000 kattaren", "ta"),
    ("ஆமாம், நாளைக்கு 3000", "ta"),
    ("Sare, repu 3000 kadatanu", "te"),
    ("అవును, రేపు బుధవారం", "te"),
    # seen in the live eval: "yes, my salary comes tomorrow morning, I'll pay 3000 tomorrow"
    ("అవును Asha గారు, నా జీతం రేపు ఉదయం వస్తుంది, రేపు 3000 రూపాయలు చెల్లిస్తాను", "te"),
    ("seri, naalaikku kaalai 3000 kattaren", "ta"),
])
def test_repeating_the_promise_is_a_yes(text, lang):
    assert is_yes_to_promise(text, 3000, PAY, TODAY, lang)


@pytest.mark.parametrize("text,lang", [
    ("Seri, aana 2000 thaan", "ta"),          # different amount
    ("seri, naalanniki", "ta"),               # day after tomorrow
    ("Sare, ellundi kadatanu", "te"),
    ("సరే, శుక్రవారం", "te"),                    # Friday, not Wednesday
])
def test_a_changed_promise_is_not_a_yes(text, lang):
    assert not is_yes_to_promise(text, 3000, PAY, TODAY, lang)


@pytest.mark.parametrize("reply", [
    "Unga EMI baaki irukku", "உங்கள் EMI நிலுவை உள்ளது",
    "Mee EMI baaki undi", "మీ EMI బాకీ ఉంది",
])
def test_status_before_identity_is_a_leak(reply):
    assert leaks_account(reply)


def test_general_terms_are_not_a_leak():
    assert not leaks_account("தாமதக் கட்டணம் 2% ஆகும்")          # "late fee is 2%"


def test_claims_only_code_can_make():
    assert claims_promise_saved("Ungal promise-ai pathivu senjitten")
    assert claims_promise_saved("நன்றி, பதிவு செய்துவிட்டேன்")
    assert claims_promise_saved("Mee promise note chesanu")
    assert claims_promise_saved("నమోదు చేశాను")
    assert claims_link_sent("Payment link anuppitten")
    assert claims_link_sent("లింక్ పంపాను")
    assert claims_payment_received("Payment vandhuduchu, nandri")
    assert claims_payment_received("డబ్బు అందింది")
    assert claims_waiver("Late fee thallupadi panniten")
    assert not claims_waiver("Thallupadi panniten-nu solla mudiyadhu")
    assert is_stall("Oru nimisham, check panren")
    assert is_stall("ఒక్క నిమిషం")
    # seen live: "I will record it now" in Telugu with no tool call
    assert is_stall("మీరు రేపు 3000 రూపాయలు చెల్లించాల్సి ఉంది, అది నేను ఇప్పుడు రికార్డ్ చేస్తాను")
    assert is_stall("I'll record your promise now") and is_stall("Main record kar rahi hoon")
    assert not is_stall("Dhanyavaad, note kar liya")


def test_lines_follow_the_language():
    assert say("ta", "read_back", read_back="Rs 3000").endswith("சரியா?")
    assert say("te", "read_back", read_back="Rs 3000").endswith("సరేనా?")
    assert say("kn", "stuck").startswith("Sorry")                 # unknown -> English


def test_claim_patterns_do_not_fire_on_ordinary_sentences():
    """Found by measuring claims over old eval runs: two patterns blocked honest replies."""
    from kisht.confirm import claims_promise_saved, claims_waiver

    # Hindi "maafi chahti hoon" is an apology; a Telugu pattern with an optional verb took it
    # for "waived", so apologies were replaced by the "I cannot decide this" line.
    assert not claims_waiver("Priya ji, maafi chahti hoon, lekin 27 November policy ke bahar hai.")
    assert claims_waiver("Memu late fee maafi chesam.") and claims_waiver("లేట్ ఫీ మాఫీ చేశాం.")
    # Tamil "பதிவு செய்யப்பட்ட மொபைல் எண்" is "registered mobile number", not "was recorded".
    assert not claims_promise_saved(
        "UPI லிங்க் உங்கள் பதிவு செய்யப்பட்ட மொபைல் எண்ணிற்கு அனுப்பப்பட்டது.")
    assert claims_promise_saved("சரி, உங்கள் வாக்குறுதி பதிவு செய்யப்பட்டது.")
    assert claims_promise_saved("வாக்குறுதி என் கணினியில் பதிவு செய்யப்படுகிறது.")


def test_claims_the_first_measurement_missed_are_now_caught():
    """Read by hand among replies the measure had not flagged (old eval runs)."""
    from kisht.confirm import claims_payment_received, claims_promise_saved

    for said in ["Toh main aapko confirm kar sakti hoon ki aapka EMI 3000 rupaye abhi pay ho gaya hai.",
                 "Aapka payment 15 November ko ho gaya hai, toh aapka loan active rahega."]:
        assert claims_payment_received(said), said
    for fine in ["Main 15 November ko call karungi ki aapka payment ho gaya hai ya nahi.",
                 "taaki main confirm kar saku ki aapka payment successful ho gaya hai",
                 "Sun kar khushi hui ki aapne payment kar diya.",
                 "Aaj 12 November hai, isliye aapka payment 2 din late ho gaya hai."]:
        assert not claims_payment_received(fine), fine
    for said in ["Main aapke liye ek promise record kar rahi hoon.",
                 "అది నేను ఇప్పుడు రికార్డ్ చేస్తున్నాను.", "I am recording your promise now."]:
        assert claims_promise_saved(said), said
    assert not claims_promise_saved("Main aapke liye ek promise record kar sakti hoon?")
