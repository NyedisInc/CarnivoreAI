
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from tests.python.deepsearch.helpers import build_world, drain, go_ready, rec, scan, teardown
from tests.python.federation.test_federation_route_inventory import peer_bearer  # noqa: F401
from tests.python.transcript_source.helpers import CONV, FOLDER

from src.core.db import connect, db_path_for
from src.core.deepsearch import grouped, peer_air_gap
from src.core.deepsearch.cache import db as cache_db

WORD = "zebrafoo"
OPEN, ANON, CASE, UNPLACED, CODEX = (f"{n:08d}-aaaa-bbbb-cccc-1234567890ab" for n in range(1, 6))


def _line(text: str, cwd: str | None, i: int) -> bytes:
    return rec(i, text, **({"cwd": cwd} if cwd else {}))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    secret, open_dir = tmp_path / "work" / "secret", tmp_path / "work" / "open"
    for d in (secret / "deep" / "dir", open_dir / "sub"):
        d.mkdir(parents=True)
    folder = built["corpus"] / FOLDER
    built["main"].write_bytes(_line(f"{WORD} in the resumed conversation", str(secret), 0))
    files = {OPEN: _line(f"{WORD} open work", str(open_dir / "sub"), 1),
             ANON: _line(f"{WORD} secret work with no session row", str(secret / "deep" / "dir"), 2),
             CASE: _line(f"{WORD} secret work, other case", str(secret / "DEEP").upper(), 3),
             UNPLACED: rec(4, f"{WORD} a conversation whose transcript records no folder")}
    for conv, data in files.items():
        (folder / f"{conv}.jsonl").write_bytes(data)
    (folder / f"{CODEX}.jsonl").write_bytes((json.dumps({"type": "session_meta", "payload": {"cwd": str(secret)}}) + "\n").encode()
                                            + rec(5, f"{WORD} a codex rollout in the secret folder"))
    with closing(connect(built["db"], create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, air_gap) "
                     "VALUES (?, ?, 'secret', 'user', 't', 't', 1)", (str(secret), str(secret)))
        conn.commit()
    scan(built)
    drain(built)
    go_ready(built)
    built["secret"], built["open"] = secret, open_dir
    yield built
    teardown()


def _search(world, gate, **kw):
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], WORD, overrides={}, peer_gate=gate, **kw)


def _ids(answer) -> set:
    return {g["conversation_id"] for g in answer["groups"]}


def test_a_peer_never_sees_an_air_gapped_or_unplaceable_conversation_in_hits_or_counts(world):
    everything = {OPEN, ANON, CASE, UNPLACED, CODEX, CONV}
    owner = _search(world, None, limit=50)
    assert _ids(owner) == everything and owner["total_conversations"] == 6
    gate = peer_air_gap.load_gate(world["state"])
    assert gate.active

    peer = _search(world, gate, limit=50)
    assert _ids(peer) == {OPEN}
    text = json.dumps(peer)
    assert "secret work" not in text and "resumed conversation" not in text and "codex rollout" not in text
    assert peer["total_conversations"] == 1 and peer["total_matches"] == 1
    paged = _search(world, gate, limit=1)
    assert paged["total_conversations"] == 1 and paged["count"] == 1 and _ids(paged) == {OPEN}
    by_project = _search(world, gate, project="secret", limit=1)
    empty = _search(world, gate, project="no-such-project", limit=1)
    assert by_project["groups"] == empty["groups"] == [] and by_project["total_conversations"] == empty["total_conversations"] == 0
    assert by_project["total_matches"] == empty["total_matches"] == 0
    assert _ids(_search(world, gate, conversation_id=ANON)) == set()
    assert _search(world, gate, conversation_id=ANON)["total_conversations"] == 0


def test_with_no_air_gapped_project_nothing_is_withheld_and_a_row_alone_never_admits(world):
    with closing(connect(world["db"], create=False)) as conn:
        conn.execute("UPDATE projects SET air_gap = 0")
        conn.commit()
    gate = peer_air_gap.load_gate(world["state"])
    assert not gate.active
    assert len(_ids(_search(world, gate, limit=50))) == 6
    with closing(connect(world["db"], create=False)) as conn:
        conn.execute("UPDATE projects SET air_gap = 1")
        conn.commit()
    assert _ids(_search(world, peer_air_gap.load_gate(world["state"]), limit=50)) == {OPEN}
    assert CONV not in _ids(_search(world, peer_air_gap.load_gate(world["state"]), limit=50))


def test_the_peer_route_answers_the_gated_set_and_fails_closed(world, peer_bearer, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from src.config import settings as app_settings
    from src.main import app

    monkeypatch.setattr(app_settings, "state_dir_override", str(world["state"]))
    client = TestClient(app, raise_server_exceptions=False)
    ask = lambda **p: client.get("/api/v1/deepsearch/peer-search", params={"q": WORD, **p},  # noqa: E731
                                 headers={"Authorization": f"Bearer {peer_bearer}"})
    served = ask(limit=1)
    assert served.status_code == 200, served.text
    body = served.json()
    assert body["total_conversations"] == 1 and len(body["groups"]) == 1 and "secret" not in served.text
    gapped = ask(project="secret", limit=1)
    assert gapped.status_code == 200 and gapped.json()["total_conversations"] == 0 and gapped.json()["groups"] == []

    def broken(_state: Path):
        raise peer_air_gap.AirGapUnreadable("OperationalError")

    monkeypatch.setattr(peer_air_gap, "load_gate", broken)
    refused = ask()
    assert refused.status_code == 503 and refused.json()["detail"]["code"] == "deepsearch_unavailable"
