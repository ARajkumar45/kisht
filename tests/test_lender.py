from datetime import time

import pytest
import yaml

from kisht.lender import ConfigError, LenderRegistry, load_lender

DEMO = "lenders/demo-nbfc.yaml"


def test_demo_lender_loads_with_rbi_window():
    lender = load_lender(DEMO)
    assert lender.contact.window.contains(time(8, 0))
    assert lender.contact.window.contains(time(18, 59))
    assert not lender.contact.window.contains(time(19, 0))
    assert not lender.contact.window.contains(time(7, 59))
    assert "waiver" in lender.needs_human and "police" in lender.banned_phrases


def edited(tmp_path, **changes):
    with open(DEMO) as f:
        data = yaml.safe_load(f)
    for dotted, value in changes.items():
        node = data
        *parents, leaf = dotted.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    path = tmp_path / "l.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.parametrize("change", [
    {"languages__default": "ta"},                       # default not allowed
    {"contact__window": {"start": "19:00", "end": "08:00"}},
    {"promises__min_part_payment_pct": 0},
    {"needs_human": ["free_money"]},
    {"id": "Demo NBFC"},
    {"surprise": True},                                  # unknown key
])
def test_bad_policies_are_rejected(tmp_path, change):
    with pytest.raises(ConfigError):
        load_lender(edited(tmp_path, **change))


def test_registry_is_multi_tenant(tmp_path):
    reg = LenderRegistry.from_dir("lenders")
    assert reg.get("demo-nbfc").agent_name == "Asha"
    with pytest.raises(ConfigError, match="unknown lender"):
        reg.get("nope")
