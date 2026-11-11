
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.federation import peer_terminal_proxy as proxy  # noqa: E402


class _Reply:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Client:
    def __init__(self, reply):
        self.reply = reply
        self.paths = []

    async def request(self, method, path, **kw):
        self.paths.append((method, path))
        return self.reply


class _Socket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


def test_pane_facts_become_a_measured_frame():
    client = _Client(_Reply(200, {"cols": 163, "rows": 46, "cwd": "/x"}))
    frame = json.loads(asyncio.run(proxy.measured_frame_from_peer(client, "ses_a")))
    assert frame == {"type": "terminal_size", "cols": 163, "rows": 46, "measured": True}
    assert client.paths == [("GET", "/sessions/ses_a/pane-facts")]


def test_an_unreadable_pane_or_a_refusal_sends_nothing():
    assert asyncio.run(proxy.measured_frame_from_peer(_Client(_Reply(200, {"cols": None, "rows": None})), "s")) is None
    assert asyncio.run(proxy.measured_frame_from_peer(_Client(_Reply(404, {})), "s")) is None


def test_the_fallback_is_skipped_once_the_owner_measures(monkeypatch):
    monkeypatch.setattr(proxy.peer_listing, "owner_session_id", lambda key, name: "ses_a")
    ws = _Socket()
    measure = proxy._Measure(_Client(_Reply(200, {"cols": 90, "rows": 30})), "peer-x", "carnivore_mac")
    asyncio.run(measure._read(ws, 0))
    assert [json.loads(t)["cols"] for t in ws.sent] == [90]
    measure.owner_sends = True
    asyncio.run(measure._read(ws, 0))
    assert len(ws.sent) == 1
