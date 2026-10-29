
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from src.core.federation import peer_deepsearch, peer_fanout
from src.core.federation.peer_fanout import PeerAnswer
from src.core.deepsearch.reader import ConversationIndex
from src.main import app
from tests.python.federation.test_federation_route_inventory import peer_bearer  # noqa: F401

STUDIO = "peer-studio"
SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def _hit(snippet: str, **more):
    return {"line": 4, "kind": "user", "snippet": snippet, "score": 1.5, "file_kind": "conversation",
            "point_id": 9, "frame_offset": 77, **more}


def _group(cid: str, snippet: str = "the \x02flux\x03 capacitor", **more):
    return {"conversation_id": cid, "matches": 2, "by_kind": {"user": 2}, "by_file_kind": {"conversation": 2},
            "session_uuid": f"sess-{cid}", "session": "work", "project_id": 7, "project": "p", "first_prompt": "hi",
            "working_dir": "/Users/someone/secret/dir", "last_active": "2026-10-01", "family": "claude",
            "hits": [_hit(snippet)], **more}


def _answer(*groups):
    return {"query": "flux", "tokens": ["flux"], "kinds": [], "total_conversations": len(groups), "total_matches": 2 * len(groups),
            "offset": 0, "count": len(groups), "groups": list(groups), "stale": [], "frames_read": 0, "live_bytes_read": 0}


def test_search_merges_peer_hits_tags_dedupes_and_names_a_dead_peer(tmp_path, monkeypatch):
    asked = []
    replies = {"v": [PeerAnswer(STUDIO, "studio", _answer(_group("c2"), _group("c3", f"leaked {SECRET} here", evil={"x": 1})))]}

    async def fake(path, open_db, links=None):
        asked.append(path)
        return replies["v"]

    monkeypatch.setattr(peer_fanout, "ask_peers", fake)
    conv = ConversationIndex(tmp_path)
    monkeypatch.setattr(conv, "_read", lambda work: _answer(_group("c1"), _group("c2")))

    body = asyncio.run(conv.search("flux", kinds=["user"], limit=20, peers=True))
    by_id = {g["conversation_id"]: g for g in body["groups"]}
    assert set(by_id) == {"c1", "c2", "c3"} and body["total_conversations"] == 3 and body["local_total_conversations"] == 2
    assert by_id["c1"]["host_key"] == "local" and by_id["c3"]["host_key"] == STUDIO and by_id["c3"]["host_label"] == "studio"
    assert by_id["c2"]["host_key"] == "local" and by_id["c2"]["also_on"] == ["studio"]
    peer_group = by_id["c3"]
    assert SECRET not in peer_group["hits"][0]["snippet"] and "evil" not in peer_group and "point_id" not in peer_group["hits"][0]
    assert peer_group["session_uuid"] is None and peer_group["working_dir"] is None
    assert body["peer_unavailable"] == [] and "kinds=user" in asked[0] and asked[0].startswith("/deepsearch/peer-search?")

    replies["v"] = [PeerAnswer(STUDIO, "studio", None, "timeout")]
    body = asyncio.run(conv.search("flux", peers=True))
    assert [g["conversation_id"] for g in body["groups"]] == ["c1", "c2"]
    assert body["peer_unavailable"] == [{"host_key": STUDIO, "host_label": "studio", "reason": "timeout"}]

    asked.clear()
    asyncio.run(conv.search("flux", offset=20, peers=True))
    asyncio.run(conv.search("flux", project="12", peers=True))
    assert asked == []


def test_a_peer_request_is_answered_locally_redacted_and_never_fans_out(peer_bearer, monkeypatch, tmp_path):  # noqa: F811
    async def boom(*a, **k):
        raise AssertionError("a peer-originated request must not ask another computer")

    async def local(self, q, **kw):
        assert kw["peers"] is False and kw["offset"] == 0
        return _answer(_group("c1", f"key {SECRET}"))

    monkeypatch.setattr(peer_fanout, "ask_peers", boom)
    monkeypatch.setattr(ConversationIndex, "search", local)
    monkeypatch.setattr(deepsearch_peer_routes.flip, "state", lambda _d: "ready")
    monkeypatch.setattr(deepsearch_peer_routes.app_settings, "state_dir_override", str(tmp_path))
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {peer_bearer}"}
    served = client.get("/api/v1/deepsearch/peer-search", params={"q": "flux"}, headers=head)
    assert served.status_code == 200, served.text
    body = served.json()
    assert SECRET not in served.text and "/Users/someone" not in served.text and body["groups"][0]["working_dir"] is None
    assert client.get("/api/v1/deepsearch/peer-search", params={"q": "flux"}).status_code == 401
    assert peer_deepsearch.export(_answer())["groups"] == []


import json  # noqa: E402
import sqlite3  # noqa: E402

from src.api import deepsearch_peer_routes  # noqa: E402
from src.core.federation.peer_hosts import PeerRow  # noqa: E402
from src.core.deepsearch import rules as rules_mod  # noqa: E402
from src.core.deepsearch.extract import extract  # noqa: E402
from src.core.deepsearch.grouped import describe  # noqa: E402
from src.core.deepsearch.query import SEARCH_QUERY_MAX_CHARS, tokens_of  # noqa: E402
from src.core.deepsearch.search import snippet  # noqa: E402


def _line(text: str) -> bytes:
    return (json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode()


def test_h1_m1_a_token_is_starred_before_indexing_and_before_any_window_cuts_it():
    text = f"here is {SECRET} then " + "filler " * 14 + "needle after it"
    found = extract(_line(text), rules_mod.effective({}, "claude"), "claude")
    assert found is not None and SECRET[4:] not in found[1] and "a1B2c3D4" not in found[1]
    assert not [t for t in tokens_of(found[1]) if t.lower().startswith(("a1b2", "ghp_a1"))]
    cut = snippet(found[1], ["needle"])
    assert "needle" in cut and "a1B2c3D4" not in cut and SECRET[4:12] not in cut


def test_h1_the_first_prompt_is_redacted_before_the_160_char_cut():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE conversation_index (conversation_id TEXT, session_uuid TEXT, project_id INT, project_name TEXT, "
                 "session_name TEXT, first_prompt TEXT, working_dir TEXT, agent_family TEXT)")
    conn.execute("INSERT INTO conversation_index VALUES ('c1', NULL, NULL, NULL, NULL, ?, NULL, NULL)", ("x" * 150 + SECRET,))
    assert "a1B2" not in describe(conn, ["c1"])["c1"]["first_prompt"]


def test_h1_a_peer_string_is_redacted_before_the_2000_char_cut():
    group = peer_deepsearch.clean_group(_group("c9", "y" * 1990 + SECRET))
    assert "a1B2c3D4" not in group["hits"][0]["snippet"]


def test_m3_a_nan_score_drops_that_hit_and_local_results_stay(tmp_path, monkeypatch):
    bad = _group("c3")
    bad["hits"] = [_hit("ok \x02flux\x03", score=float("nan")), _hit("fine \x02flux\x03", score=2.0)]
    bad["matches"] = float("nan")
    merged = peer_deepsearch.merge({"groups": [{"conversation_id": "c1"}], "total_conversations": 1, "total_matches": 1},
                                   [PeerAnswer(STUDIO, "studio", _answer(bad))])
    json.dumps(merged, allow_nan=False)
    peer = next(g for g in merged["groups"] if g["conversation_id"] == "c3")
    assert [h["score"] for h in peer["hits"]] == [2.0] and peer["matches"] == 1
    assert any(g["conversation_id"] == "c1" for g in merged["groups"])


def test_m4_a_deeply_nested_peer_body_costs_only_that_peer(monkeypatch):
    class Reply:
        status_code = 200

        def json(self):
            return json.loads("[" * 200_000 + "]" * 200_000)

    class Client:
        async def request(self, *a, **k):
            return Reply()

    class Links:
        def client(self, _id):
            return Client()

    peer = PeerRow.__new__(PeerRow)
    monkeypatch.setattr(peer_fanout.peer_hosts, "list_peers", lambda conn: [type("P", (), {"key": STUDIO, "label": "studio", "peer_install_id": "i"})()])
    monkeypatch.setattr(peer_fanout.direction, "is_one_way_toward", lambda _i: False)
    answers = asyncio.run(peer_fanout.ask_peers("/x", lambda: sqlite3.connect(":memory:"), Links()))
    assert len(answers) == 1 and answers[0].data is None and answers[0].reason == "bad_answer"
    del peer


def test_not_ready_peer_answer_is_named_not_an_error():
    merged = peer_deepsearch.merge({"groups": []}, [PeerAnswer(STUDIO, "studio", peer_deepsearch.not_ready_answer("flux"))])
    assert merged["peer_unavailable"] == [{"host_key": STUDIO, "host_label": "studio", "reason": "not_ready"}]


def test_peer_route_m1_and_the_lows(peer_bearer, monkeypatch, tmp_path):  # noqa: F811
    seen = []

    async def local(self, q, **kw):
        seen.append(q)
        return _answer(_group("c1"))

    monkeypatch.setattr(ConversationIndex, "search", local)
    monkeypatch.setattr(deepsearch_peer_routes.app_settings, "state_dir_override", str(tmp_path))
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {peer_bearer}"}
    get = lambda q="flux": client.get("/api/v1/deepsearch/peer-search", params={"q": q}, headers=head)  # noqa: E731

    monkeypatch.setattr(deepsearch_peer_routes.flip, "state", lambda _d: "building")
    not_ready = get().json()
    assert not_ready["not_ready"] is True and not_ready["groups"] == [] and seen == []

    monkeypatch.setattr(deepsearch_peer_routes.flip, "state", lambda _d: "ready")
    assert get().status_code == 200 and seen == ["flux"]
    assert get("ab").json()["groups"] == [] and seen == ["flux"]
    assert get("a flux").status_code == 200 and seen[-1] == "flux"
    assert get("x" * (SEARCH_QUERY_MAX_CHARS + 1)).status_code in (400, 422)

    monkeypatch.setattr(deepsearch_peer_routes, "_inflight", peer_deepsearch.PEER_MAX_INFLIGHT)
    assert get().status_code == 429
    monkeypatch.setattr(deepsearch_peer_routes, "_inflight", 0)


def test_the_requester_cuts_a_long_query_to_the_peer_cap(tmp_path, monkeypatch):
    asked = []

    async def fake(path, open_db, links=None):
        asked.append(path)
        return []

    monkeypatch.setattr(peer_fanout, "ask_peers", fake)
    conv = ConversationIndex(tmp_path)
    monkeypatch.setattr(conv, "_read", lambda work: _answer(_group("c1")))
    asyncio.run(conv.search("z" * 400, peers=True))
    from urllib.parse import parse_qs, urlsplit
    assert len(parse_qs(urlsplit(asked[0]).query)["q"][0]) == SEARCH_QUERY_MAX_CHARS


def test_search_peers_is_peers_alone_and_never_waits_on_local(tmp_path, monkeypatch):
    async def fake(path, open_db, links=None):
        return [PeerAnswer(STUDIO, "studio", _answer(_group("c2")))]

    monkeypatch.setattr(peer_fanout, "ask_peers", fake)
    conv = ConversationIndex(tmp_path)
    monkeypatch.setattr(conv, "_read", lambda work: (_ for _ in ()).throw(AssertionError("local index must not be read")))
    body = asyncio.run(conv.search_peers("flux"))
    assert [g["conversation_id"] for g in body["groups"]] == ["c2"] and body["groups"][0]["host_key"] == STUDIO
    assert asyncio.run(conv.search_peers("flux", offset=20))["groups"] == []


def test_m3_bigint_and_lone_surrogate_drop_the_peer_and_local_results_stay(caplog):
    from fastapi.responses import JSONResponse

    local = {"groups": [{"conversation_id": "c1"}], "total_conversations": 1, "total_matches": 1}
    huge = json.loads("1" + "0" * 400)
    lone = json.loads('"a\\ud800b"')
    for bad_hit in (_hit("x \x02flux\x03", score=huge), _hit(lone)):
        group = _group("c3")
        group["hits"] = [bad_hit]
        merged = peer_deepsearch.merge(local, [PeerAnswer(STUDIO, "studio", _answer(group))])
        JSONResponse(merged)
        assert [g["conversation_id"] for g in merged["groups"] if g["host_key"] != "local"] == ["c3"] and merged["groups"][-1]["hits"] == []
    for field in ({"project": lone}, {"conversation_id": lone}):
        merged = peer_deepsearch.merge(local, [PeerAnswer(STUDIO, "studio", _answer({**_group("c4"), **field}))])
        JSONResponse(merged)
        assert not any(g["conversation_id"] in ("c4", lone) and g.get("project") for g in merged["groups"])


def test_m3_an_unforeseen_validation_failure_drops_only_that_peer(monkeypatch):
    local = {"groups": [{"conversation_id": "c1"}], "total_conversations": 1, "total_matches": 1}
    real = peer_deepsearch.clean_group

    def boom(raw):
        if raw.get("conversation_id") == "boom":
            raise OverflowError("unforeseen")
        return real(raw)

    monkeypatch.setattr(peer_deepsearch, "clean_group", boom)
    merged = peer_deepsearch.merge(local, [PeerAnswer(STUDIO, "studio", _answer(_group("c2"), _group("boom")))])
    assert [g["conversation_id"] for g in merged["groups"]] == ["c1"] and merged["peer_unavailable"]


def test_l1_the_peer_slot_is_held_until_the_scan_thread_finishes(monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()

    async def slow(self, q, **kw):
        await asyncio.to_thread(lambda: (started.set(), release.wait(5)))
        return _answer(_group("c1"))

    monkeypatch.setattr(ConversationIndex, "search", slow)
    monkeypatch.setattr(deepsearch_peer_routes.flip, "state", lambda _d: "ready")
    monkeypatch.setattr(deepsearch_peer_routes, "_inflight", 0)

    async def scenario():
        call = asyncio.ensure_future(deepsearch_peer_routes.peer_search(
            q="flux", kinds=None, project=None, conversation_id=None, limit=5, per_group=2))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        call.cancel()
        await asyncio.sleep(0.05)
        held = deepsearch_peer_routes._inflight
        release.set()
        for _ in range(100):
            if deepsearch_peer_routes._inflight == 0:
                break
            await asyncio.sleep(0.02)
        return held, deepsearch_peer_routes._inflight

    held, after = asyncio.run(scenario())
    assert held == 1 and after == 0


def test_h1_a_per_block_cut_redacts_before_it_cuts():
    from src.core.deepsearch.extract import _apply

    assert "a1B2c3D4" not in _apply(40, "x" * 30 + SECRET)
