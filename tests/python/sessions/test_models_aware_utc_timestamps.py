
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.encoders import jsonable_encoder

from src.core import toast_auto_ack, toast_history
from src.models import LocalServerInfo, LogEntry, Session, Toast
from src.models.utc_time import as_aware_utc, seconds_since, utc_now

NAIVE_ROW = "2026-01-01T12:00:00"


def _toast(created_at: datetime, tid: str = "t", kind: str = "Stop") -> Toast:
    return Toast(id=tid, session_id="ses_1", kind=kind, title="done", created_at=created_at)


def test_new_records_are_aware_utc() -> None:
    session = Session(id="ses_1", working_dir="/tmp")
    records = [
        session.created_at, session.last_activity,
        LogEntry(session_id="ses_1", content="x").timestamp,
        LocalServerInfo(port=5173, url="u").first_seen,
        _toast(utc_now()).created_at,
    ]
    assert all(stamp.utcoffset() == timedelta(0) for stamp in records)


def test_an_old_naive_row_loads_as_utc_beside_a_new_aware_one() -> None:
    old = Session.model_validate({"id": "ses_old", "working_dir": "/tmp", "created_at": NAIVE_ROW, "last_activity": NAIVE_ROW})
    new = Session(id="ses_new", working_dir="/tmp")
    assert old.created_at == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert (new.created_at - old.created_at).total_seconds() > 0
    assert sorted([new.created_at, old.created_at])[0] == old.created_at
    assert _toast(datetime(2026, 1, 1, 12, 0)).created_at.tzinfo is not None


def test_uptime_subtraction_accepts_naive_and_aware_stamps() -> None:
    now = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    assert seconds_since(datetime(2026, 1, 1, 12, 0), now) == 30
    assert seconds_since(datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), now) == 30
    assert seconds_since(utc_now()) == 0
    assert as_aware_utc(datetime(2026, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))).hour == 12


def test_the_auto_ack_cutoff_compares_a_naive_cutoff_against_an_aware_toast() -> None:
    cutoff = utc_now().replace(tzinfo=None) - timedelta(seconds=5)
    later = _toast(utc_now(), "later", "PermissionRequest")
    assert toast_auto_ack.resolve_auto_acks([later], "Stop", cutoff=cutoff) == []
    earlier = _toast(utc_now() - timedelta(seconds=60), "earlier", "PermissionRequest")
    assert toast_auto_ack.resolve_auto_acks([earlier], "Stop", cutoff=cutoff) == ["earlier"]


def test_toast_history_sorts_a_naive_assignment_with_aware_records() -> None:
    aware = _toast(utc_now(), "aware")
    stale = _toast(utc_now(), "stale")
    stale.created_at = datetime(2026, 1, 1)
    ordered = toast_history.collect_toasts({"ses_1": [stale, aware]})
    assert [t.id for t in ordered] == ["aware", "stale"]


@pytest.mark.parametrize("model", ["session", "log", "toast"])
def test_the_json_wire_carries_an_offset_the_clients_parse(model: str) -> None:
    record = {
        "session": Session(id="ses_1", working_dir="/tmp"),
        "log": LogEntry(session_id="ses_1", content="x"),
        "toast": _toast(utc_now()),
    }[model]
    for payload in (json.loads(record.model_dump_json()), jsonable_encoder(record)):
        stamps = [v for k, v in payload.items() if k in {"created_at", "last_activity", "timestamp"}]
        assert stamps
        for text in stamps:
            assert text.endswith("Z") or text.endswith("+00:00"), text
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            assert parsed.utcoffset() == timedelta(0)
