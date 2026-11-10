from kisht.audit import AuditLog, mask_phone


def test_phone_numbers_are_masked():
    assert mask_phone("call +91 98450 12345 now") == "call ******2345 now"
    assert mask_phone("9845012345") == "******2345"
    assert mask_phone("98450-12345") == "******2345"


def test_dates_amounts_and_ids_are_not_masked():
    for text in ["2026-11-10", "2026-11-10T11:00", "EMI 12500", "LN-000123", "ref 20261110"]:
        assert mask_phone(text) == text


def test_record_masks_nested_values_and_checks_outcome(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    e = log.record(call_id="c1", tenant_id="demo-nbfc", action="verify_identity",
                   args={"phone": "9845012345", "due": "2026-11-15"}, outcome="ok")
    assert e["args"] == {"phone": "******2345", "due": "2026-11-15"}
    assert (tmp_path / "a.jsonl").read_text().count("\n") == 1
    assert log.for_call("c1") == [e]
