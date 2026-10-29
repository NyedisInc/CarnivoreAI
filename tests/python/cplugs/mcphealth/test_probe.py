
from datetime import datetime, timedelta, timezone

from src.core.mcp_health.probe import ProbeResult, ProbeTable, classify_status, probe_once
from tests.python.cplugs.mcphealth.http_fixture import StubMcpServer, free_port


def test_down_then_reachable_on_the_same_port():
    port = free_port()
    stub = StubMcpServer(port)
    first = probe_once(stub.url, "http", timeout=2)
    assert (first.reachable, first.reason, first.detail) == (False, "refused", "ECONNREFUSED")
    stub.start()
    try:
        second = probe_once(stub.url, "http", timeout=2)
        assert (second.reachable, second.reason, second.detail) == (True, "reachable", "200")
        method, headers = stub.requests[-1]
        assert method == "POST"
        assert not any(k.lower() in ("authorization", "cookie") for k in headers)
    finally:
        stub.stop()


def test_401_is_reachable_with_auth_unknown_not_down():
    stub = StubMcpServer(free_port(), status=401).start()
    try:
        got = probe_once(stub.url, "http", timeout=2)
        assert (got.reachable, got.reason, got.detail) == (True, "auth_required", "401")
    finally:
        stub.stop()


def test_5xx_and_404_are_down():
    for status, reason in ((503, "server_error"), (404, "not_found")):
        stub = StubMcpServer(free_port(), status=status).start()
        try:
            got = probe_once(stub.url, "http", timeout=2)
            assert (got.reachable, got.reason, got.detail) == (False, reason, str(status))
        finally:
            stub.stop()


def test_a_minted_session_is_deleted_and_sse_is_a_get():
    stub = StubMcpServer(free_port(), session_id="abc123").start()
    try:
        probe_once(stub.url, "http", timeout=2)
        assert [m for m, _ in stub.requests] == ["POST", "DELETE"]
        assert stub.requests[1][1].get("Mcp-Session-Id") == "abc123"
        probe_once(stub.url, "sse", timeout=2)
        assert stub.requests[-1][0] == "GET" and stub.requests[-1][1].get("Accept") == "text/event-stream"
    finally:
        stub.stop()


def test_status_table():
    assert classify_status(200) == (True, "reachable")
    assert classify_status(405) == (True, "reachable")
    assert classify_status(403) == (True, "auth_required")
    assert classify_status(410) == (False, "not_found")
    assert classify_status(502) == (False, "server_error")


def test_table_probes_each_unique_url_once_per_interval_and_forgets_unwanted():
    calls = []
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)

    def fake(url, transport):
        calls.append(url)
        return ProbeResult(True, "reachable", "200", now)

    table = ProbeTable(probe=fake, interval=timedelta(seconds=60))
    try:
        wanted = {("http", "http://a/mcp"), ("http", "http://b/mcp")}
        assert table.refresh(wanted | {("http", "http://a/mcp")}, now) is True
        assert sorted(calls) == ["http://a/mcp", "http://b/mcp"]
        assert table.refresh(wanted, now + timedelta(seconds=30)) is False and len(calls) == 2
        table.refresh({("http", "http://a/mcp")}, now + timedelta(seconds=61))
        assert table.get("http", "http://b/mcp") is None and len(calls) == 3
    finally:
        table.close()
