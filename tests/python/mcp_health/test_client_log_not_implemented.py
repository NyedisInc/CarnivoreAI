
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.core.mcp_health import client_log
from src.core.mcp_health.servers import REASON_CONNECT_FAILED, REASON_NOT_IMPLEMENTED, STATE_DOWN

NOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


def _line(text: str, key: str = "error") -> bytes:
    return json.dumps({key: text, "timestamp": "2026-10-28T14:00:04.196Z"}).encode()


def _link(*lines: bytes):
    state = client_log._FileState()
    for line in lines:
        client_log._apply(state, line)
    return client_log.link_from_state("claude-artifacts", state, NOW)


def test_a_404_connection_failure_is_not_implemented():
    link = _link(_line("Connection failed after 544ms, 544ms of it awake (404): Error POSTing to endpoint: not found\n", "debug"),
                 _line("Connection failed (404): Error POSTing to endpoint: not found\n"))
    assert (link.state, link.reason) == (STATE_DOWN, REASON_NOT_IMPLEMENTED)


def test_a_501_connection_failure_is_not_implemented():
    assert _link(_line("Connection failed (501): not implemented\n")).reason == REASON_NOT_IMPLEMENTED


def test_other_failures_stay_a_plain_connect_failure():
    assert _link(_line("Connection failed (500): boom\n")).reason == REASON_CONNECT_FAILED
    assert _link(_line("Connection failed (ENOENT)\n")).reason == REASON_CONNECT_FAILED
    assert _link(_line("Connection failed (ETIMEDOUT): slow\n")).reason == REASON_CONNECT_FAILED
