
from __future__ import annotations

import re

from tests.python.federation.test_federation_route_inventory import _peer_scopes, _routes
from src.core.federation import peer_forward


def _session_routes():
    return [(m, p.replace("/api/v1", "", 1), r) for m, p, r in _routes()
            if p.startswith("/api/v1") and peer_forward.is_session_path(p.replace("/api/v1", "", 1))]


def test_every_session_route_has_a_row() -> None:
    walked = _session_routes()
    assert len(walked) > 80, "the walk saw too few session routes to mean anything"
    missing = [(m, p) for m, p, _ in walked if (m, p) not in peer_forward.RULES]
    assert missing == [], f"add a forward, refuse or local row to peer_forward.TABLE for: {missing}"


def test_the_table_has_no_stale_row() -> None:
    have = {(m, p.replace("/api/v1", "", 1)) for m, p, _ in _routes()}
    assert [k for k in peer_forward.RULES if k not in have] == []


def test_a_forward_row_names_a_real_parameter_and_takes_a_peer_token() -> None:
    for method, path, route in _session_routes():
        rule = peer_forward.RULES[(method, path)]
        tagged = bool(_peer_scopes(route))
        if rule.mode == peer_forward.SELF:
            assert tagged, f"{method} {path} relays itself so must take a peer token"
            continue
        if rule.mode != peer_forward.FORWARD:
            listing = (method, path) in (("GET", "/sessions/list"), ("GET", "/sessions/asleep"), ("GET", "/sessions/list-and-asleep"))
            assert not tagged or listing, f"{method} {path} is {rule.mode} but takes a peer token"
            continue
        assert tagged, f"{method} {path} is forwarded but refuses a peer token at the owner"
        where, name, form = rule.ref
        if where == "path":
            assert "{" + name + "}" in path
        elif where == "query":
            assert name in {q.name for q in route.dependant.query_params}, (method, path, name)
        else:
            assert method in ("POST", "PUT", "PATCH", "DELETE") and name, (method, path)
        assert form in (peer_forward.NAME, peer_forward.UUID, peer_forward.SID)


def test_a_refused_row_says_why_and_a_forward_row_does_not_need_to() -> None:
    assert all(r.why for r in peer_forward.TABLE if r.mode == peer_forward.REFUSE)


def test_the_rule_lookup_prefers_a_static_path() -> None:
    assert peer_forward.rule_for("POST", "/api/v1/sessions/recreate").ref == ("body", "session_uuid", "uuid")
    assert peer_forward.rule_for("PATCH", "/api/v1/sessions/remote:peer-x:n/name").ref == ("path", "session_id", "sid")
    assert peer_forward.rule_for("GET", "/api/v1/nothing") is None
    assert re.fullmatch(r"[a-z]+", peer_forward.FORWARD)


def test_local_transcript_operations_and_task_manager_candidates_stay_local() -> None:
    for method, path in (("POST", "/sessions/ses_1/fork-to"),
                         ("GET", "/sessions/ses_1/prompt-texts")):
        rule = peer_forward.rule_for(method, "/api/v1" + path)
        assert rule.mode == peer_forward.REFUSE
        assert rule.why
    listing = peer_forward.rule_for("GET", "/api/v1/cplugs/huddle/lists/shared/sessions")
    assert listing.mode == peer_forward.LOCAL
