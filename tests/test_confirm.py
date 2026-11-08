import pytest

from receptionist.confirm import (
    claims_availability,
    claims_booking,
    is_clear_yes,
    safe_reply_instead_of_false_claim,
)


@pytest.mark.parametrize("text", [
    "yes", "Yes please", "yeah sure", "ok", "Okay, book it", "go ahead", "correct",
    "haan", "Haan ji", "ji haan", "theek hai", "haan, book kar do", "bilkul",
    "haan sahi hai", "kar dijiye", "no problem, book it", "haan koi baat nahi",
    "हाँ", "जी हाँ", "ठीक है", "हाँ, बुक कर दो", "बिल्कुल",
])
def test_clear_yes(text):
    assert is_clear_yes(text)


@pytest.mark.parametrize("text", [
    "", "no", "nahi", "ji nahi", "not now", "wait", "ruko", "hmm",
    "yes but make it 12", "haan lekin shaam ko", "can you change it to Tuesday",
    "is it at 11?", "haan?", "don't book it", "mat karo", "dusra time batao",
    "what is the price", "Priya",
    # a yes that names another time, number or day is a change, not a yes
    "Theek hai, 12 baje kar do", "ok, make it 12", "yes, 11:30 please", "haan shaam ko",
    "sure, Tuesday instead", "ok but later", "theek hai, kal kar do",
    "नहीं", "जी नहीं", "हाँ लेकिन शाम को", "ठीक है, 12 बजे कर दो", "रुको", "हाँ?",
])
def test_not_a_clear_yes(text):
    assert not is_clear_yes(text)


@pytest.mark.parametrize("reply", [
    "Done, I've booked your haircut for 11 AM.",
    "Your appointment is confirmed for Tuesday.",
    "Booked! See you tomorrow.",
    "Aapka haircut book kar diya hai.",
    "Booking ho gayi, kal milte hain.",
    "You're all set for 4 PM.",
])
def test_reply_claims_a_booking(reply):
    assert claims_booking(reply)


@pytest.mark.parametrize("reply", [
    "Shall I book it?",
    "Men's haircut with Ravi on Tuesday at 11:00 AM. Shall I book it?",
    "It's not booked yet, should I go ahead?",
    "Kya main book kar doon?",
    "We have 10:00 and 10:30 free.",
])
def test_reply_does_not_claim_a_booking(reply):
    assert not claims_booking(reply)


def test_safe_reply_reads_back_the_pending_booking():
    pending = {"read_back": "Men's haircut with Ravi at 11:00 AM. Shall I book it?"}
    assert "Ravi" in safe_reply_instead_of_false_claim(pending, "en")
    assert safe_reply_instead_of_false_claim(pending, "hi").startswith("Book karne se pehle")
    assert "Nothing is booked yet" in safe_reply_instead_of_false_claim(None, "en")


@pytest.mark.parametrize("reply", [
    "Haan, facial parso shaam ko ho sakta hai.",
    "Yes, 11 AM is free tomorrow.",
    "We have slots available on Saturday.",
    "Sorry, Saturday is full.",
    "Kal shaam ko slot khali hai.",
    "Haan, 4 baje mil jayega.",
])
def test_reply_states_availability(reply):
    assert claims_availability(reply)


@pytest.mark.parametrize("reply", [
    "We're open 10 to 8 on weekdays.",
    "Our salon is open from 10:00 to 20:00 on Monday through Friday.",
    "To give you free start times, which service and which day?",
    "Which time would be free for you?",
    "A men's haircut costs Rs 300.",
    "Kis din aana chahenge?",
    "Yes, we take cash, card and UPI.",
])
def test_reply_does_not_state_availability(reply):
    assert not claims_availability(reply)
