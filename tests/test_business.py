from datetime import time
from pathlib import Path

import pytest
import yaml

from receptionist.business import (
    BusinessRegistry,
    ConfigError,
    load_business,
    normalize_phone,
)

ROOT = Path(__file__).resolve().parent.parent
SALON = ROOT / "businesses" / "glow-salon.yaml"


def salon_data():
    return yaml.safe_load(SALON.read_text(encoding="utf-8"))


def write(tmp_path, data, name="biz.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_salon_template_loads():
    b = load_business(SALON)
    assert b.business_id == "glow-salon"
    assert b.languages.default == "en"
    assert b.hours["sun"] == [(time(10), time(14))]
    assert b.service("haircut-men").duration_min == 30
    assert [p.id for p in b.staff_for("facial")] == ["meena"]


def test_every_allowed_language_needs_a_greeting(tmp_path):
    data = salon_data()
    data["languages"]["allowed"] = ["en", "hi", "kn"]
    with pytest.raises(ConfigError, match="no greeting.*kn"):
        load_business(write(tmp_path, data))


def test_staff_cannot_offer_unknown_service(tmp_path):
    data = salon_data()
    data["staff"][0]["services"].append("massage")
    with pytest.raises(ConfigError, match="unknown service"):
        load_business(write(tmp_path, data))


def test_every_service_needs_someone_to_do_it(tmp_path):
    data = salon_data()
    data["services"].append({"id": "pedicure", "name": "Pedicure", "duration_min": 30, "price_inr": 500})
    with pytest.raises(ConfigError, match="no staff member offers"):
        load_business(write(tmp_path, data))


def test_opening_must_be_before_closing(tmp_path):
    data = salon_data()
    data["hours"]["mon"] = [["20:00", "10:00"]]
    with pytest.raises(ConfigError, match="not before closing"):
        load_business(write(tmp_path, data))


def test_typo_in_a_field_name_is_caught(tmp_path):
    data = salon_data()
    data["rules"]["max_day_ahead"] = 7  # typo: should be max_days_ahead
    with pytest.raises(ConfigError):
        load_business(write(tmp_path, data))


def test_clinic_must_turn_on_emergency_check(tmp_path):
    data = salon_data()
    data["type"] = "clinic"
    with pytest.raises(ConfigError, match="emergency_check"):
        load_business(write(tmp_path, data))


def test_missing_file_gives_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_business(tmp_path / "nope.yaml")


def test_phone_numbers_match_with_or_without_spaces():
    assert normalize_phone("+91 80 0000 0001") == normalize_phone("+918000000001")


def test_registry_finds_business_by_called_number():
    reg = BusinessRegistry.from_dir(ROOT / "businesses")
    assert reg.by_called_number("+918000000001").business_id == "glow-salon"
    with pytest.raises(ConfigError, match="no business uses"):
        reg.by_called_number("+911234567890")


def test_two_businesses_cannot_share_a_number(tmp_path):
    a = salon_data()
    b = salon_data()
    b["business_id"] = "other-salon"
    write(tmp_path, a, "a.yaml")
    write(tmp_path, b, "b.yaml")
    with pytest.raises(ConfigError, match="used by both"):
        BusinessRegistry.from_dir(tmp_path)
