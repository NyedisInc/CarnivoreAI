
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.core.federation import peer_ledger, peer_merge
from src.core.federation.peer_fanout import PeerAnswer, unavailable_marker
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, UsageWindow
from tests.python.project_history.test_projects_history_route import CONV_ON_DISK, _app, seeded  # noqa: F401

STUDIO = "peer-studio"


DOWN = PeerAnswer(STUDIO, "studio", None, "timeout")


def _group(key, sessions):
    return {"key": key, "project": {"name": "p"}, "session_total": len(sessions), "counts": {"closed": len(sessions)},
            "sessions": sessions}


def _sess(uuid, conv=None, name="n"):
    return {"session_uuid": uuid, "title": name, "tmux_name": name, "state": "closed", "claude_session_uuid": conv,
            "live_session_id": "ses_theirs"}


def test_history_merge_tags_dedupes_and_names_the_down_peer():
    local = {"total": 1, "groups": []}
    held = peer_merge.Held({"conv-held"}, {(STUDIO, "shadowed")})
    answer = PeerAnswer(STUDIO, "studio", {"groups": [_group("7", [_sess("a", "conv-held"), _sess("b", None, "shadowed"), _sess("c", "conv-new")])]})
    merged = peer_merge.merge_history(local, [answer, PeerAnswer("peer-x", "other", None, "disconnected")], held)
    group = merged["peer_groups"][0]
    assert group.key == f"{STUDIO}:7" and group.host_label == "studio" and group.session_total == 1
    assert [s.session_uuid for s in group.sessions] == ["c"]
    assert group.sessions[0].host_key == STUDIO and group.sessions[0].live_session_id is None
    assert merged["peer_unavailable"] == [{"host_key": "peer-x", "host_label": "other", "reason": "disconnected"}]
    bad = peer_merge.merge_history(local, [PeerAnswer(STUDIO, "studio", {"groups": [{"nope": 1}]})], held)
    assert bad["peer_groups"] == [] and bad["peer_unavailable"][0]["reason"] == "bad_answer"


def test_history_route_carries_peer_groups_and_survives_a_dead_peer(seeded, monkeypatch):  # noqa: F811
    from src.api import projects_history_routes as routes

    answers = {"v": [PeerAnswer(STUDIO, "studio", {"groups": [_group("7", [_sess("z", CONV_ON_DISK)])]})]}
    seen = []

    async def fake(path, open_db, links=None):
        seen.append(path)
        return answers["v"]

    monkeypatch.setattr(routes.peer_fanout, "ask_peers", fake)
    client = _app()
    body = client.get("/api/v1/projects/history", params={"q": "alpha"}).json()
    assert len(body["groups"]) >= 1 and body["peer_groups"] == []
    assert "q=alpha" in seen[0] and "offset" not in seen[0]
    answers["v"] = [DOWN]
    body = client.get("/api/v1/projects/history").json()
    assert body["state"] == "ok" and body["total"] == 3 and body["peer_unavailable"][0]["reason"] == "timeout"
    seen.clear()
    client.get("/api/v1/projects/history", params={"offset": 1})
    assert seen == []



SECRET_KEY = re.compile(r"token|secret|password|cookie|authorization|refresh|pointer|config_dir|codex_home|email|identity$|profile",
                        re.I)
ALLOWED = {"provider", "name", "short_name", "plan", "credential_state", "fetched_at", "windows", "identity_key"}


def _snapshot():
    now = datetime.now(timezone.utc)
    win = [UsageWindow(kind="five_hour", label="5h", used_pct=40.0, window_seconds=18000)]

    def acct(i, provider, identity):
        return AccountUsage(id=i, name=i, provider=provider, plan="max", identity=identity, credential_state="ok",
                            fetched_at=now, windows=win, managed=True, login_expires_at=now)

    return LedgerSnapshot(accounts=[acct("a", "claude", "Me@Example.com"), acct("b", "codex", None)],
                          total=LedgerTotal(accounts=2), loop=LoopStatus(alive=True))


def _walk_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_keys(v)


def test_the_served_summary_carries_no_secret_shaped_key_and_no_email():
    payload = peer_ledger.summary_of(_snapshot()).model_dump(mode="json")
    keys = set(_walk_keys(payload))
    assert not [k for k in keys if SECRET_KEY.search(k)]
    assert set(payload["accounts"][0]) == ALLOWED
    assert "example.com" not in json.dumps(payload).lower()


def test_a_field_added_to_the_summary_goes_red():
    assert set(peer_ledger.SummaryAccount.model_fields) == ALLOWED
    with pytest.raises(ValidationError):
        peer_ledger.SummaryAccount(provider="claude", name="x", credential_state="ok", token="sk-x")


def test_a_shared_account_is_flagged_once_and_an_unknown_identity_never_matches():
    served = peer_ledger.summary_of(_snapshot()).model_dump(mode="json")
    merged = peer_ledger.merge(_snapshot(), [PeerAnswer(STUDIO, "studio", served), DOWN.__class__("peer-x", "other", None, "timeout")])
    shared = {a.name: a.shared for a in merged.peers[0].accounts}
    assert shared == {"a": True, "b": False}
    assert merged.peer_unavailable == [{"host_key": "peer-x", "host_label": "other", "reason": "timeout"}]
    assert peer_ledger.identity_key("claude", " ME@example.com ") == peer_ledger.identity_key("claude", "me@example.com")
    assert peer_ledger.identity_key("claude", None) is None


def test_a_peer_summary_with_a_stray_field_is_refused_not_shown():
    merged = peer_ledger.merge(_snapshot(), [PeerAnswer(STUDIO, "studio", {"accounts": [{"provider": "claude", "name": "x", "credential_state": "ok", "token": "t"}]})])
    assert merged.peers == [] and merged.peer_unavailable[0]["reason"] == "bad_answer"


def test_marker_helper_lists_only_the_silent():
    assert unavailable_marker([PeerAnswer(STUDIO, "studio", {"hits": []}), DOWN]) == [{"host_key": STUDIO, "host_label": "studio", "reason": "timeout"}]
