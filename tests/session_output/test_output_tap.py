
from __future__ import annotations

from types import SimpleNamespace

from src.core.session_manager import SessionManager
from src.core.session_output import tap as output_tap
from src.core.session_output.tap import OutputTap


def test_no_observer_is_a_no_op_and_session_observers_see_only_their_session():
    tap = OutputTap()
    tap.emit("ses_1", b"x")
    seen = []
    tap.add(lambda sid, data: seen.append(("all", sid, data)))
    tap.add(lambda sid, data: seen.append(("one", sid, data)), session_id="ses_1")
    tap.emit("ses_1", b"a")
    tap.emit("ses_2", b"b")
    assert seen == [("all", "ses_1", b"a"), ("one", "ses_1", b"a"), ("all", "ses_2", b"b")]


def test_a_raising_observer_is_switched_off_and_never_stops_the_others():
    tap = OutputTap()
    seen = []

    def broken(_sid, _data):
        raise RuntimeError("boom")

    tap.add(broken, session_id="ses_1")
    tap.add(lambda sid, data: seen.append(data), session_id="ses_1")
    tap.emit("ses_1", b"1")
    tap.emit("ses_1", b"2")
    assert seen == [b"1", b"2"]
    assert tap.observer_count("ses_1") == 1
    tap.remove(broken, session_id="ses_1")


def test_the_output_handler_fans_out_then_emits_into_the_tap(monkeypatch):
    published, tapped = [], []
    fake = SimpleNamespace(_registry=SimpleNamespace(publish=lambda sid, data: published.append((sid, data))))
    tap = OutputTap()
    tap.add(lambda sid, data: tapped.append((sid, data)))
    monkeypatch.setattr(output_tap, "TAP", tap)
    handler = SessionManager._make_output_handler(fake, "ses_9")
    assert handler(b"chunk") is None
    assert published == tapped == [("ses_9", b"chunk")]
