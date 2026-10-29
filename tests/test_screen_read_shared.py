
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from src.core.account_switch import auto_restart
from src.core.attention import screen_read
from src.core.attention.screen_reuse import ScreenReuse
from src.core.attention_reader import AttentionEvidenceReader


def _row(activity: int) -> dict:
    return {"pane_is_current": True, "pane_dead": "0", "pane_id": "%1", "pid": 11, "created_at_epoch": 7,
            "pane_width": 80, "pane_height": 24, "window_activity": activity}


def test_two_readers_in_one_pass_cause_one_capture(monkeypatch):
    captures = []

    def fake_capture(socket, name, history=0, row=None):
        captures.append((socket, name))
        return "prompt\n"

    monkeypatch.setattr(screen_read, "subprocess", SimpleNamespace(run=None, TimeoutExpired=Exception))
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(fake_capture))
    monkeypatch.setattr(auto_restart, "capture_screen", fake_capture)
    shared = ScreenReuse()
    reader = AttentionEvidenceReader(SimpleNamespace(), lambda key: (None, None), screens=shared)
    evidence = auto_restart.SessionEvidence(
        SimpleNamespace(tmux_socket_name=lambda: "cloude", claude_uuid_for_tmux_name=lambda name: None), screens=shared)

    async def no_transcript(info):
        return None

    evidence._transcript_stop = no_transcript  # type: ignore[method-assign]
    row = _row(int(time.time()) - 600)
    assert reader._screen_text("cloude", "cloude_a", row) == "prompt\n"
    assert asyncio.run(evidence.limit_stop(SimpleNamespace(tmux_session="cloude_a"), row=row)) is None
    assert reader._screen_text("cloude", "cloude_a", row) == "prompt\n"
    assert captures == [("cloude", "cloude_a")]
