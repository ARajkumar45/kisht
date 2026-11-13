"""Lender policy (one YAML per lender = multi-tenant). The guard reads every limit from here."""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal["en", "hi", "kn", "ta", "te"]
HumanReason = Literal["waiver", "settlement", "restructure", "dispute", "hardship", "bereavement",
                      "wrong_person", "complaint"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Languages(_Strict):
    allowed: list[Language] = Field(min_length=1)
    default: Language

    @model_validator(mode="after")
    def _default_is_allowed(self) -> Languages:
        if self.default not in self.allowed:
            raise ValueError(f"default language {self.default!r} is not in allowed")
        return self


class Window(_Strict):
    start: time
    end: time

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.start >= self.end:
            raise ValueError("contact window start must be before end")
        return self

    def contains(self, t: time) -> bool:
        return self.start <= t < self.end


class Contact(_Strict):
    window: Window
    max_attempts_per_day: int = Field(ge=1)
    max_attempts_per_week: int = Field(ge=1)
    channels: list[Literal["chat", "voice"]] = Field(min_length=1)
    # While the human desk has an open case of one of these kinds, the agent does not contact
    # the borrower at all (RBI 2026 recovery directions, 100Y(6): bereavement, medical
    # emergencies and the like are occasions to avoid).
    hold_while_open: list[str] = ["hardship", "bereavement", "dispute"]
    recording_notice: bool = True      # voice: say that the call is recorded (100P)


class GrievanceOfficer(_Strict):
    """Carried on every written recovery message (RBI 2026 recovery directions, 100AA)."""
    name: str
    email: str
    phone: str
    address: str

    def line(self) -> str:
        return (f"Grievance officer: {self.name}, {self.email}, {self.phone}, {self.address}")


class Promises(_Strict):
    max_days_after_due: int = Field(ge=0)
    min_part_payment_pct: int = Field(ge=1, le=100)
    max_open_promises: int = Field(1, ge=1)


class QAItem(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    check: str                       # what a reviewer looks for, in plain words


# Collections QA scorecard, after common contact-centre practice and the RBI Fair Practices
# Code for recovery (identify yourself, verify the borrower, no pressure, record what was
# agreed). A lender can replace it in its YAML.
DEFAULT_SCORECARD = [
    QAItem(id="introduced", check="The agent said who they are and which lender they call from."),
    QAItem(id="verified_first", check="Identity was verified before any loan detail was shared."),
    QAItem(id="explained_dues", check="The amount and date due were explained simply and "
                                      "correctly."),
    QAItem(id="asked_reason", check="The agent asked what is stopping the payment before "
                                    "pushing an option."),
    QAItem(id="fitting_option", check="The agent offered an option that fits what the borrower "
                                      "said (pay now, promise, part payment, or hand-off)."),
    QAItem(id="clear_commitment", check="Any promise or payment was read back with amount and "
                                        "date and confirmed by the borrower."),
    QAItem(id="respectful", check="The agent was polite and patient, with no pressure, threats "
                                  "or shaming."),
    QAItem(id="right_handoff", check="Hardship, disputes, waiver or settlement requests and "
                                     "wrong-person calls were handed to a human."),
    QAItem(id="clear_close", check="The call ended with a clear next step."),
]


class Lender(_Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    agent_name: str
    agent_gender: Literal["female", "male"] = "female"
    timezone: str = "Asia/Kolkata"
    languages: Languages
    contact: Contact
    promises: Promises
    needs_human: list[HumanReason]
    banned_phrases: list[str]
    escalation_desk: str
    grievance_officer: GrievanceOfficer | None = None
    desk_teams: dict[str, str] = {}               # escalation reason -> human team
    desk_sla_hours: dict[str, float] = {}         # escalation reason -> hours to resolve
    qa_scorecard: list[QAItem] = DEFAULT_SCORECARD

    def sla_hours_for(self, reason: str) -> float:
        return self.desk_sla_hours.get(reason, self.desk_sla_hours.get("default", 24))

    def team_for(self, reason: str) -> str:
        return self.desk_teams.get(reason, self.desk_teams.get("default", "Collections desk"))

    @field_validator("banned_phrases")
    @classmethod
    def _lowercase(cls, v: list[str]) -> list[str]:
        return [p.strip().lower() for p in v if p.strip()]


class ConfigError(Exception):
    pass


def load_lender(path: str | Path) -> Lender:
    try:
        with open(path, encoding="utf-8") as f:
            return Lender.model_validate(yaml.safe_load(f))
    except (OSError, yaml.YAMLError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from e


class LenderRegistry:
    def __init__(self, lenders: list[Lender]):
        self._by_id: dict[str, Lender] = {}
        for lender in lenders:
            if lender.id in self._by_id:
                raise ConfigError(f"duplicate lender id {lender.id!r}")
            self._by_id[lender.id] = lender

    @classmethod
    def from_dir(cls, directory: str | Path) -> LenderRegistry:
        return cls([load_lender(p) for p in sorted(Path(directory).glob("*.yaml"))])

    def get(self, lender_id: str) -> Lender:
        try:
            return self._by_id[lender_id]
        except KeyError:
            raise ConfigError(f"unknown lender {lender_id!r}") from None

    def ids(self) -> list[str]:
        return list(self._by_id)
