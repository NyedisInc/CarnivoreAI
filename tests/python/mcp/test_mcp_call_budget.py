from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import mcp_launch
from src.core.mcp import call_budget, tools
from src.core.mcp_bridge import stdio_bridge
from tests.python.mcp.test_mcp_endpoint import _hdr, _rpc, env  # noqa: F401


@pytest.mark.parametrize("value,expected", [
    (None, 50.0), ("", 50.0), ("abc", 50.0), ("0", 50.0), ("60", 50.0), ("120", 95.0), ("900", 600.0), ("625", 600.0), ("500", 475.0),
    ("86401", 50.0), ("100", 75.0),
])
def test_from_header_table(value, expected) -> None:
    assert call_budget.from_header(value) == expected


def test_current_outside_a_request_is_the_floor() -> None:
    assert call_budget.current() == 50.0
    with call_budget.using(77):
        assert call_budget.current() == 77.0
    assert call_budget.current() == 50.0


def test_the_three_spellings_of_the_header_agree() -> None:
    assert stdio_bridge.TOOL_TIMEOUT_HEADER == call_budget.HEADER == mcp_launch.TOOL_TIMEOUT_HEADER


def test_every_client_declares_its_limit() -> None:
    doc = mcp_launch._http_server_doc(False)
    assert doc["timeout"] == 120000 and doc["headers"][call_budget.HEADER] == "120"
    args = mcp_launch.codex_args("http://127.0.0.1:1/mcp")
    assert any(a.startswith("mcp_servers.carnivore.http_headers=") and call_budget.HEADER in a
               and f'"{mcp_launch.CODEX_TOOL_TIMEOUT_SEC}"' in a for a in args)
    assert stdio_bridge.REQUEST_TIMEOUT_S == 900.0
    up = stdio_bridge.Upstream(SimpleNamespace(token="t", session_ref="", channel=False), None)  # type: ignore[arg-type]
    assert up.headers()[call_budget.HEADER] == "900"


@pytest.mark.parametrize("header,expected", [("120", 95.0), (None, 50.0)])
def test_a_tool_handler_sees_the_budget(env, monkeypatch, header, expected) -> None:
    client, mgr, _ = env
    seen: list[float] = []

    async def handler(manager, caller, args):
        seen.append(call_budget.current())
        return tools._ok({"ok": True})

    row = tools._TOOLS["whoami"]
    monkeypatch.setitem(tools._TOOLS, "whoami", (*row[:3], handler, *row[4:]))
    headers = _hdr(mgr)
    if header:
        headers[call_budget.HEADER] = header
    r = client.post("/mcp", json=_rpc("tools/call", {"name": "whoami", "arguments": {}}), headers=headers)
    assert r.status_code == 200, r.text
    assert seen == [expected]
