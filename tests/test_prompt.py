from datetime import date

from receptionist.prompt import build_messages, stable_prefix, system_message

MON = date(2026, 11, 9)


def test_prefix_identical_across_turns_and_calls(salon):
    call_a_turn_1 = build_messages(salon, [{"role": "user", "content": "hi"}], MON)
    call_a_turn_5 = build_messages(salon, [{"role": "user", "content": "hi"}] * 5, MON)
    call_b = build_messages(salon, [{"role": "user", "content": "namaste"}], MON)
    first = call_a_turn_1[0]["content"]
    assert call_a_turn_5[0]["content"] == first
    assert call_b[0]["content"] == first
    assert first.encode() == system_message(salon, MON)["content"].encode()  # byte-identical


def test_only_the_date_line_changes_between_days(salon):
    mon = system_message(salon, MON)["content"]
    tue = system_message(salon, date(2026, 11, 10))["content"]
    prefix = stable_prefix(salon)
    assert mon.startswith(prefix) and tue.startswith(prefix)
    assert mon != tue


def test_calendar_spells_out_kal_parso_and_every_weekday(salon):
    text = system_message(salon, MON)["content"]
    assert "Monday 2026-11-09 = today (aaj)" in text
    assert "Tuesday 2026-11-10 = tomorrow (kal)" in text
    assert "Wednesday 2026-11-11 = day after tomorrow (parso)" in text
    assert "Saturday 2026-11-14" in text            # the date the model got wrong
    assert "Monday 2026-11-16" in text              # next week's Monday is there too
    assert "Tuesday 2026-11-17" not in text         # but no more than 8 days


def test_prefix_has_the_business_facts(salon):
    prefix = stable_prefix(salon)
    assert "Glow Salon" in prefix
    assert "- haircut-men: Men's haircut, 30 min, Rs 300 (Ravi)" in prefix
    assert "- Sunday: 10:00-14:00" in prefix
    assert "Q: Is there parking?" in prefix


def test_owner_phone_is_not_given_to_the_model(salon):
    assert salon.owner.phone not in stable_prefix(salon)
    assert "90000" not in stable_prefix(salon)


def test_notebook_comes_after_system_message_unchanged(salon):
    notebook = [{"role": "assistant", "content": "Hello"}, {"role": "user", "content": "hi"}]
    messages = build_messages(salon, notebook, MON)
    assert messages[0]["role"] == "system"
    assert messages[1:] == notebook
