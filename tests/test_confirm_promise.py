"""D88: borrowers confirm a promise by repeating it. Words that agree with the pending
promise must not block the yes; anything that disagrees still does."""
from datetime import date

import pytest

from kisht.confirm import is_yes_to_promise

TODAY, PAY = date(2026, 11, 10), date(2026, 11, 11)   # promise is for tomorrow (Wednesday)


@pytest.mark.parametrize("text", [
    "haan",
    "Haan ji, bilkul sahi, kal 11 November ko main 3000 rupaya kar dungi.",
    "Yes, Rs 3,000 on Wednesday is fine",
    "हाँ जी, कल 3000 दे दूंगी",
])
def test_repeating_the_promise_is_a_yes(text):
    assert is_yes_to_promise(text, 3000, PAY, TODAY)


@pytest.mark.parametrize("text", [
    "Haan, par 2000 hi de paungi",       # different amount
    "theek hai, 15 November ko",         # different date
    "haan, parso kar dungi",             # day after tomorrow, not tomorrow
    "nahi, kal nahi",
    "haan?",
])
def test_a_change_is_not_a_yes(text):
    assert not is_yes_to_promise(text, 3000, PAY, TODAY)
