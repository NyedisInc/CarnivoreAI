
from __future__ import annotations

import time

from structlog.testing import capture_logs

from src.api.request_log import RequestLogMiddleware
from src.core.mcp import protocol, tools
from src.cplugs.host import mcp as cplug_mcp, state as owner_state
from src.cplugs.host.runtime import Host


def _count_state_reads(monkeypatch) -> list:
    reads: list = []
    real = owner_state.get

    def counting(state_dir, manifest):
        reads.append(manifest.id)
        return real(state_dir, manifest)

    monkeypatch.setattr(owner_state, "get", counting)
    return reads


def test_tools_list_reads_state_once_per_plugin(monkeypatch) -> None:
    owners = set(cplug_mcp._OWNERS.values())
    assert len(cplug_mcp._OWNERS) > len(owners)
    reads = _count_state_reads(monkeypatch)
    tools.tool_definitions(None)
    print(f"state reads per tools/list: {len(reads)} for {len(cplug_mcp._OWNERS)} plugin tools")
    assert len(reads) == len(set(reads)) <= len(owners)


def test_a_plugin_switch_is_seen_by_the_next_list(monkeypatch) -> None:
    owner = next(iter(cplug_mcp._OWNERS.values()))
    names = {n for n, o in cplug_mcp._OWNERS.items() if o == owner}
    state = {"on": True}
    monkeypatch.setattr(Host, "enabled", lambda self, cid: state["on"] if cid == owner else True)
    assert names & {d["name"] for d in tools.tool_definitions(None)}
    state["on"] = False
    assert not names & {d["name"] for d in tools.tool_definitions(None)}


def test_the_request_log_line_names_the_rpc_method() -> None:
    assert protocol.rpc_methods(b'[{"method": "tools/list"}, {"method": "ping"}]') == "tools/list,ping"
    assert protocol.rpc_methods(b"not json") == ""
    with capture_logs() as logs:
        RequestLogMiddleware._log("POST", "/mcp", "127.0.0.1", 200, time.perf_counter(), {"rpc": "tools/list"})
    assert logs[0]["rpc"] == "tools/list" and logs[0]["path"] == "/mcp"
