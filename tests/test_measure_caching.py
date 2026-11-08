"""The M3 script's pieces that need no model server."""
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "measure_caching.py"
spec = importlib.util.spec_from_file_location("measure_caching", SCRIPT)
mc = importlib.util.module_from_spec(spec)
sys.modules["measure_caching"] = mc      # dataclasses need the module registered
spec.loader.exec_module(mc)


def test_notebook_grows_one_user_turn_at_a_time():
    n1 = mc.notebook_at(1, "Hello")
    n3 = mc.notebook_at(3, "Hello")
    assert [m["role"] for m in n1] == ["assistant", "user"]
    assert [m["role"] for m in n3] == ["assistant", "user", "assistant", "user", "assistant", "user"]
    assert n3[-1]["content"] == "Kal 11 baje slot hai kya?"
    assert n3[:2] == n1                      # earlier turns are a prefix of later ones


def test_prefix_marker_goes_first_in_the_system_message():
    msgs = [{"role": "system", "content": "RULES"}, {"role": "user", "content": "hi"}]
    out = mc.with_prefix(msgs, "[x] ")
    assert out[0]["content"] == "[x] RULES" and out[1] == msgs[1]
    assert msgs[0]["content"] == "RULES"      # original untouched


def test_summary_table_has_all_three_conditions_and_cold_warm():
    rows = [mc.Row("conditions", c, call, t, 1400, cached, 20, ttft, ttft + 1)
            for c, cached, ttft in (("stable", 1350, 0.3), ("per-call", 700, 0.8), ("none", 0, 2.0))
            for call in (1, 2) for t in (1, 2)]
    rows.append(mc.Row("cold_start", "cold", 1, 1, 1400, 0, 1, 3.0, 3.0))
    rows.append(mc.Row("cold_start", "warm", 1, 2, 1400, 1390, 1, 0.3, 0.3))
    rows.append(mc.Row("interleaved", "salon", 1, 1, 1400, 0, 20, 2.0, 3.0))
    table = mc.summarize(rows)
    assert "| stable |" in table and "| per-call |" in table and "| none |" in table
    assert "96%" in table                     # 1350/1400 cached share for stable
    assert "(cold)" in table and "(warm)" in table and "salon, call 2" in table
    assert "Interleaved" in table


def test_other_business_differs_only_in_identity():
    from receptionist.business import load_business
    salon = load_business(Path(__file__).resolve().parent.parent / "businesses" / "glow-salon.yaml")
    other = mc.other_business(salon)
    assert other.name == "Lotus Salon" and other.services == salon.services
