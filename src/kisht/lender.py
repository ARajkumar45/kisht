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


class Promises(_Strict):
    max_days_after_due: int = Field(ge=0)
    min_part_payment_pct: int = Field(ge=1, le=100)
    max_open_promises: int = Field(1, ge=1)


class Lender(_Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    agent_name: str
    timezone: str = "Asia/Kolkata"
    languages: Languages
    contact: Contact
    promises: Promises
    needs_human: list[HumanReason]
    banned_phrases: list[str]
    escalation_desk: str

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
