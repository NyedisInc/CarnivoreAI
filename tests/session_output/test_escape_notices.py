
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.session_output import escape_notices as en
from src.core.session_output.escape_scanner import Event


class _Hub:
    def __init__(self):
        self.frames = []

    def publish(self, frame):
        self.frames.append(frame)
        return 1


class _Manager:
    def __init__(self, mute=False):
        self.toasts, self.mute = [], mute
        self._notification_policy_store = object()

    def notification_policy_stamp(self, session_id):
        return SimpleNamespace(muted=self.mute)

    def record_toast(self, **kw):
        self.toasts.append(kw)
        from src.models import Toast
        return Toast(id="t%d" % len(self.toasts), session_id=kw["session_id"], kind=kw["kind"],
                     title=kw["title"], body=kw["body"], created_at="2026-10-30T00:00:00Z")


def _notices(monkeypatch, mute=False, gate=True):
    clock = [100.0]
    notices = en.TerminalNotices(clock=lambda: clock[0])
    hub, manager, sent = _Hub(), _Manager(mute), []
    monkeypatch.setattr(en, "get_hub", lambda app_state: hub)
    monkeypatch.setattr(en.session_change_notice, "publish", lambda app_state, frame: 1)
    monkeypatch.setattr(en, "resolve_raise", lambda *a, **k: SimpleNamespace(raises_toast=gate))
    notices._manager, notices._send = manager, lambda sid, payload: sent.append(sid)
    return notices, clock, hub, manager


def test_clean_strips_controls_and_bidi_and_caps_bytes():
    assert en.clean("ok‮\x07\x1b done\n", 160) == "ok done"
    assert len(en.clean("é" * 300, 160).encode()) <= 160


def test_a_burst_of_three_then_one_every_five_seconds(monkeypatch):
    notices, clock, _, manager = _notices(monkeypatch)
    for _ in range(5):
        notices._notify("ses_1", Event("notify", "t", "b"))
    assert len(manager.toasts) == 3
    clock[0] += 5.0
    notices._notify("ses_1", Event("notify", "t", "b"))
    assert len(manager.toasts) == 4 and manager.toasts[0]["notify_type"] == "session.terminal_notice"


def test_mute_claude_and_codex_raise_no_card(monkeypatch):
    notices, _, _, manager = _notices(monkeypatch, gate=False)
    notices._notify("ses_1", Event("notify", "t", "b"))
    notices2, _, _, manager2 = _notices(monkeypatch)
    notices2.on_observation("ses_2", "working", "claude")
    notices2._notify("ses_2", Event("notify", "t", "b"))
    assert manager.toasts == [] and manager2.toasts == [] and notices2.recorded_quiet == 1


def test_a_secret_in_the_body_is_masked(monkeypatch):
    notices, _, _, manager = _notices(monkeypatch)
    notices._notify("ses_1", Event("notify", "", "token ghp_" + "a" * 36))
    assert "a" * 36 not in manager.toasts[0]["body"] and manager.toasts[0]["title"] == en.DEFAULT_TITLE


def test_progress_frame_only_on_change_and_cleared_by_silence_or_death(monkeypatch):
    notices, clock, hub, _ = _notices(monkeypatch)
    notices._set_progress("ses_1", ("normal", 40))
    notices._set_progress("ses_1", ("normal", 40))
    clock[0] += en.PROGRESS_GAP_SECONDS
    notices._set_progress("ses_1", ("normal", 41))
    assert [f["percent"] for f in hub.frames] == [40, 41]
    clock[0] += 16
    notices.on_observation("ses_1", "working", "custom")
    notices._set_progress("ses_2", ("indeterminate", None))
    notices.on_observation("ses_2", "dead", "custom")
    cleared = [f["session_id"] for f in hub.frames if f["state"] is None]
    assert cleared == ["ses_1", "ses_2"] and len(hub.frames) == 5


def test_a_stream_of_changing_progress_codes_sends_one_frame_per_gap_and_the_tick_sends_the_last(monkeypatch):
    notices, clock, hub, _ = _notices(monkeypatch)
    for pct in range(1, 501):
        notices._set_progress("ses_1", ("normal", pct % 2))
    notices._set_progress("ses_1", ("normal", 77))
    assert [f["percent"] for f in hub.frames] == [1]
    clock[0] += 2.0
    notices.on_observation("ses_1", "working", "custom")
    notices.on_observation("ses_1", "working", "custom")
    assert [f["percent"] for f in hub.frames] == [1, 77]


def test_a_credential_split_by_a_format_character_is_still_redacted(monkeypatch):
    notices, _, _, manager = _notices(monkeypatch)
    token = "ghp_" + "\u202e" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    notices._notify("ses_1", Event("notify", "deploy " + token, "body " + token))
    card = manager.toasts[0]
    assert "A1b2C3d4" not in card["title"] and "A1b2C3d4" not in card["body"]


def test_the_output_path_only_queues_and_one_drain_raises(monkeypatch):
    notices, _, hub, manager = _notices(monkeypatch)

    async def run():
        notices.on_output("ses_1", b"\x1b]9;one\x07\x1b]9;4;1;5\x07")
        notices.on_output("ses_1", b"\x07")
        assert manager.toasts == [] and hub.frames == []
        await asyncio.sleep(0)

    asyncio.run(run())
    assert len(manager.toasts) == 1
    assert [f["type"] for f in hub.frames] == ["session.progress", "session.bell"]
