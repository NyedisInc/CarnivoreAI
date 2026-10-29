
from __future__ import annotations

import re
import sys
from pathlib import Path

from src.cplugs.host import mcp_health_port

PACKAGE = Path(__file__).resolve().parents[4] / "packages" / "cplugs" / "mcphealth"
sys.path.insert(0, str(PACKAGE))
import mh_combine  # noqa: E402
import mh_vocab  # noqa: E402

sys.path.remove(str(PACKAGE))

FIELD_STATES = frozenset({"connected", "down", "needs_auth", "unknown"})
FIELD_TRANSPORTS = frozenset({"stdio", "http", "sse", "proxy", "unknown"})
FIELD_SOURCES = frozenset({"client_log", "first_hand", "probe", "process", "transcript", "server"})
FIELD_REASON = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
FIELD_KNOWN_REASONS = frozenset({
    "refused", "dns", "timeout", "tls", "unreachable", "server_error", "not_found", "reachable", "auth_required", "gave_up", "closed",
    "connect_failed", "reconnecting", "process_gone", "process_running", "connected", "needs_auth", "not_seen", "transcript"})


def _judged(specs, links):
    linked = {mh_vocab.server_key(n): mh_vocab.Link(n, "http", s, r) for n, (s, r) in links.items()}
    return {h.name: h for h in mh_combine.judge_session(mh_combine.Evidence(tuple(specs), links=linked))}


def test_a_log_only_404_reads_unknown_and_raises_no_drop():
    out = _judged([], {"claude-artifacts": ("down", "not_implemented")})
    assert (out["claude-artifacts"].state, out["claude-artifacts"].reason) == ("unknown", "not_found")
    assert mh_combine.as_drops(out.values()) == []


def test_a_configured_server_with_a_404_still_warns():
    spec = mh_vocab.ServerSpec("mine", "http", scope="user")
    out = _judged([spec], {"mine": ("down", "not_implemented")})
    assert out["mine"].state == "down"
    assert [d["name"] for d in mh_combine.as_drops(out.values())] == ["mine"]


def test_any_other_log_only_failure_still_warns():
    out = _judged([], {"claude-artifacts": ("down", "connect_failed"), "claude.ai X": ("down", "gave_up")})
    assert {h.state for h in out.values()} == {"down"}
    assert len(mh_combine.as_drops(out.values())) == 2


def test_every_value_the_sidecar_sends_is_accepted_by_the_field_hosts():
    out = _judged([], {"claude-artifacts": ("down", "not_implemented"), "claude.ai X": ("down", "connect_failed"),
                       "plugin:x:y": ("connected", "connected")})
    for health in out.values():
        assert health.state in FIELD_STATES
        assert health.transport in FIELD_TRANSPORTS
        assert health.source in FIELD_SOURCES
        assert FIELD_REASON.match(health.reason)
        assert health.reason in FIELD_KNOWN_REASONS
    assert not hasattr(mh_vocab, "STATE_UNAVAILABLE") and not hasattr(mcp_health_port, "STATE_UNAVAILABLE")
