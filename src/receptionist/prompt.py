"""Build the model request in a stable order (D36):

  system message = [fixed instructions]      identical for every call of every business
                 + [business knowledge]      identical for every call to this business
                 + [today's date line]       changes once a day
  then the call's notebook                   changes every turn

Everything before the date line is byte-identical across turns and calls, so the
model server can reuse its cached work. The date line comes last in the system
message because step 1 showed the model needs "kal" spelled out as a date.

There is deliberately no "keep replies to one or two sentences" rule: with Qwen3.5-9B
any such length rule made the model say "let me check" instead of calling the tool
(0/12 tool calls with it, 10/12 without; replies stayed short anyway).
Nothing caller-specific (name, phone, language) goes into the system message.
"""
from __future__ import annotations

from datetime import date, timedelta

from receptionist.business import WEEKDAYS, Business

FIXED_INSTRUCTIONS = """\
You are the phone receptionist for the business described below, speaking with a caller \
on the phone.

Rules you must follow:
1. Facts (services, prices, timings, staff, address) come ONLY from the business \
knowledge below or from tool results. If you do not know something, say the owner will \
confirm and offer to take a message. Never guess.
2. Never talk about free times without calling check_availability first.
3. To book: find out the service, the day and time, the caller's name and a phone \
number. As soon as you have all four, call book_visit; do not ask the caller to confirm \
before that, and never write a read-back or confirmation question of your own. Say the \
returned read_back sentence to the caller exactly, then stop and wait for their answer.
4. You never book anything yourself: the system books it the moment the caller says yes \
to the read_back, and tells the caller. Never say something is booked.
5. If a tool returns ok=false, follow its message and tell the caller in simple words.
6. Never promise anything the owner must decide (discounts, exceptions, refunds). Offer \
to take a message for the owner instead.
7. Reply in the language the caller uses, if it is one of the business's languages. \
Hindi callers often mix Hindi and English; reply the same way.
8. Times in tool calls use the format YYYY-MM-DDTHH:MM (24-hour, local time). Dates use \
YYYY-MM-DD.
"""

_DAY_NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
              "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}
_LANG_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada", "te": "Telugu", "ta": "Tamil"}


def business_knowledge(b: Business) -> str:
    lines = [f"BUSINESS: {b.name} ({b.type})", f"Address: {b.address}",
             "Languages: " + ", ".join(_LANG_NAMES[x] for x in b.languages.allowed),
             "Opening hours:"]
    for day in WEEKDAYS:
        windows = b.hours.get(day, [])
        text = ", ".join(f"{a:%H:%M}-{z:%H:%M}" for a, z in windows) or "closed"
        lines.append(f"- {_DAY_NAMES[day]}: {text}")
    lines.append("Services (use the id in tool calls):")
    for s in b.services:
        who = ", ".join(p.name for p in b.staff_for(s.id))
        lines.append(f"- {s.id}: {s.name}, {s.duration_min} min, Rs {s.price_inr} ({who})")
    lines.append("Staff (use the id in tool calls): "
                 + ", ".join(f"{p.id} = {p.name}" for p in b.staff))
    if b.faqs:
        lines.append("Common questions:")
        lines += [f"- Q: {f.q} A: {f.a}" for f in b.faqs]
    lines.append(f"Owner: {b.owner.name}. Bookings open up to {b.rules.max_days_ahead} days "
                 f"ahead and need {b.rules.min_notice_min} minutes' notice.")
    return "\n".join(lines)


CALENDAR_DAYS = 8   # today + the next 7 days, so every weekday name has a date


def date_line(today: date) -> str:
    """Spell out dates so the model never computes them (it got 'Saturday' wrong)."""
    labels = {0: "today (aaj)", 1: "tomorrow (kal)", 2: "day after tomorrow (parso)"}
    days = []
    for i in range(CALENDAR_DAYS):
        d = today + timedelta(days=i)
        label = f" = {labels[i]}" if i in labels else ""
        days.append(f"{d:%A} {d.isoformat()}{label}")
    return "CALENDAR: " + "; ".join(days) + "."


def stable_prefix(b: Business) -> str:
    """The part that must never change between turns or calls to the same business."""
    return FIXED_INSTRUCTIONS + "\n" + business_knowledge(b) + "\n"


def system_message(b: Business, today: date) -> dict:
    return {"role": "system", "content": stable_prefix(b) + date_line(today)}


def build_messages(b: Business, notebook: list[dict], today: date) -> list[dict]:
    return [system_message(b, today), *notebook]
