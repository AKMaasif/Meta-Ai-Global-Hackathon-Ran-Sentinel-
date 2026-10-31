import pytest
from conftest import run_until
from fastapi import HTTPException

from app import main


def test_alarms_are_enriched_and_ackable(sentinel, monkeypatch):
    monkeypatch.setattr(main, "sentinel", sentinel)
    sentinel.inject("SEA-RAN-004", "hardware", 2)
    inc = run_until(sentinel, "SEA-RAN-004")
    rows = main.alarms({})
    assert rows, "the hardware fault raises alarms"
    a = next(r for r in rows if r["cell_id"] == "SEA-RAN-004")
    assert a["event_type"] != "Other" and a["probable_cause"] and a["zip_code"] and a["band"]
    assert a["incident"] == inc["id"] and a["ack"] is None
    on = main.ack_alarm(a["alarm_id"], {})
    assert on["ack"]["by"] == "Sarah Chen"
    assert next(r for r in main.alarms({}) if r["alarm_id"] == a["alarm_id"])["ack"] == on["ack"]
    assert main.ack_alarm(a["alarm_id"], {})["ack"] is None
    with pytest.raises(HTTPException):
        main.ack_alarm("no-such-alarm", {})
