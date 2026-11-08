"""Business config: one YAML file per business (D8), checked when it is loaded.

The number that was called decides which business config loads (D52).
"""
from __future__ import annotations

import re
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LanguageCode = Literal["en", "hi", "kn", "te", "ta"]


class ConfigError(Exception):
    """A business config file is missing, broken, or contradicts itself."""


def normalize_phone(number: str) -> str:
    """Keep digits and a leading +, so '+91 80 0000 0001' and '+918000000001' match."""
    number = number.strip()
    digits = re.sub(r"\D", "", number)
    return ("+" if number.startswith("+") else "") + digits


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Languages(_Strict):
    default: LanguageCode
    allowed: list[LanguageCode] = Field(min_length=1)

    @model_validator(mode="after")
    def _default_is_allowed(self):
        if self.default not in self.allowed:
            raise ValueError(f"default language {self.default!r} is not in allowed")
        return self


class Service(_Strict):
    id: str
    name: str
    duration_min: int = Field(gt=0)
    price_inr: int = Field(ge=0)


class Staff(_Strict):
    id: str
    name: str
    services: list[str] = Field(min_length=1)


class Faq(_Strict):
    q: str
    a: str


class Rules(_Strict):
    slot_step_min: int = Field(default=15, gt=0)
    min_notice_min: int = Field(default=60, ge=0)
    max_days_ahead: int = Field(default=14, gt=0)


class Owner(_Strict):
    name: str
    phone: str


class Safety(_Strict):
    emergency_check: bool = False


class Business(_Strict):
    business_id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    type: Literal["clinic", "salon", "pg"]
    address: str
    timezone: str = "Asia/Kolkata"
    phone_numbers: list[str] = Field(min_length=1)
    languages: Languages
    greeting: dict[LanguageCode, str]
    hours: dict[str, list[tuple[time, time]]]
    services: list[Service] = Field(min_length=1)
    staff: list[Staff] = Field(min_length=1)
    faqs: list[Faq] = []
    rules: Rules = Rules()
    owner: Owner
    safety: Safety = Safety()

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, hours):
        for day, windows in hours.items():
            if day not in WEEKDAYS:
                raise ValueError(f"unknown weekday {day!r}; use {', '.join(WEEKDAYS)}")
            for start, end in windows:
                if start >= end:
                    raise ValueError(f"{day}: opening {start} is not before closing {end}")
        return hours

    @model_validator(mode="after")
    def _check_references(self):
        missing = [lang for lang in self.languages.allowed if lang not in self.greeting]
        if missing:
            raise ValueError(f"no greeting for language(s): {', '.join(missing)}")
        service_ids = [s.id for s in self.services]
        if len(set(service_ids)) != len(service_ids):
            raise ValueError("service ids must be unique")
        staff_ids = [s.id for s in self.staff]
        if len(set(staff_ids)) != len(staff_ids):
            raise ValueError("staff ids must be unique")
        for person in self.staff:
            unknown = set(person.services) - set(service_ids)
            if unknown:
                raise ValueError(f"staff {person.id!r} lists unknown service(s): {sorted(unknown)}")
        for service in self.services:
            if not any(service.id in p.services for p in self.staff):
                raise ValueError(f"no staff member offers service {service.id!r}")
        if self.safety.emergency_check is False and self.type == "clinic":
            raise ValueError("clinic configs must set safety.emergency_check: true (D53)")
        return self

    def service(self, service_id: str) -> Service:
        for s in self.services:
            if s.id == service_id:
                return s
        raise KeyError(service_id)

    def staff_for(self, service_id: str) -> list[Staff]:
        return [p for p in self.staff if service_id in p.services]


def load_business(path: str | Path) -> Business:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"business config not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name}: not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: expected a mapping at the top level")
    try:
        return Business.model_validate(data)
    except ValueError as e:
        raise ConfigError(f"{path.name}: {e}") from e


class BusinessRegistry:
    """All business configs in a folder, found by the number that was called."""

    def __init__(self, businesses: list[Business]):
        self._by_id: dict[str, Business] = {}
        self._by_number: dict[str, Business] = {}
        for b in businesses:
            if b.business_id in self._by_id:
                raise ConfigError(f"duplicate business_id {b.business_id!r}")
            self._by_id[b.business_id] = b
            for number in b.phone_numbers:
                key = normalize_phone(number)
                if key in self._by_number:
                    raise ConfigError(
                        f"number {number} is used by both {self._by_number[key].business_id!r} "
                        f"and {b.business_id!r}"
                    )
                self._by_number[key] = b

    @classmethod
    def from_dir(cls, folder: str | Path) -> BusinessRegistry:
        files = sorted(Path(folder).glob("*.yaml"))
        if not files:
            raise ConfigError(f"no business configs (*.yaml) in {folder}")
        return cls([load_business(f) for f in files])

    def by_id(self, business_id: str) -> Business:
        try:
            return self._by_id[business_id]
        except KeyError:
            raise ConfigError(f"unknown business {business_id!r}") from None

    def by_called_number(self, number: str) -> Business:
        try:
            return self._by_number[normalize_phone(number)]
        except KeyError:
            raise ConfigError(f"no business uses the number {number}") from None
