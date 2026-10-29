
from __future__ import annotations

import json

import pytest

from src.core.bookmarks import locate, rows, service, store, transcript_index
from tests.python.bookmarks import fixtures

ALPHA = "crosstalk from @Carnivore thread t-1 msg m-1 This is a test. Reply with exactly the word ALPHA."
CHARLIE = "crosstalk from @Carnivore thread t-3 msg m-3 Third test turn. Reply with exactly the word CHARLIE."


def _peer(uuid: str, parent: str, body: str) -> dict:
    return fixtures._rec("user", uuid, parent, isMeta=True, promptSource="system", turnOrigin="peer",
                         origin={"kind": "peer", "name": "Carnivore", "body": body},
                         message={"role": "user", "content": f"Another Claude session sent a message:\n{body}"})


def _peer_driven() -> list:
    text = lambda t: {"type": "text", "text": t}  # noqa: E731
    return [
        fixtures._user("p1", None, ALPHA, promptSource="typed"),
        fixtures._assistant("pa1", "p1", "m1", text("ALPHA")),
        fixtures._rec("system", "ps1", "pa1", subtype="turn_duration", durationMs=5),
        _peer("p2", "ps1", CHARLIE),
        fixtures._assistant("pa2", "p2", "m2", text("CHARLIE")),
    ]


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    fixtures.write_transcript(root)
    peer_conversation = "22222222-2222-4222-8222-222222222222"
    peer_path = fixtures.write_transcript(root, conversation=peer_conversation)
    peer_path.write_text("".join(json.dumps(r) + "\n" for r in _peer_driven()), encoding="utf-8")
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    peer_db = fixtures.make_datastore(tmp_path / "peer.db", conversation=peer_conversation, session_uuid="row-peer")
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "claude")
    store.set_store(store.BookmarkStore(tmp_path / "bookmarks.db"))
    yield {"db": db, "peer_db": peer_db, "monkeypatch": monkeypatch}
    store.set_store(None)


def _on(env, which: str) -> None:
    path = env[which]
    env["monkeypatch"].setattr(rows, "db_path", lambda: path)


def test_bookmark_now_after_a_peer_turn_carries_that_turns_message(env):
    _on(env, "peer_db")
    made = service.add_bookmark("row-peer", label="before charlie", point=service.POINT_NOW, created_by="claude")
    assert made.entry_uuid == "pa2"
    assert "CHARLIE" in made.snippet and "ALPHA" not in made.snippet


def test_a_point_inside_an_earlier_turn_carries_that_turns_prompt(env):
    _on(env, "peer_db")
    assert "ALPHA" in service.add_bookmark("row-peer", entry_uuid="pa1", created_by="claude").snippet
    _on(env, "db")
    assert service.add_bookmark("row-uuid-1", entry_uuid="a3", created_by="claude").snippet == "second prompt"
    assert service.add_bookmark("row-uuid-1", point=service.POINT_NOW, created_by="claude").snippet == "third prompt"


def test_a_peer_turn_opens_a_turn_but_is_not_a_typed_prompt():
    peer = transcript_index.node_from_record(_peer("p", "x", CHARLIE), 0, 1)
    assert peer.turn_start and not peer.prompt and not peer.stop and peer.snippet == " ".join(CHARLIE.split())
    reply = transcript_index.node_from_record(fixtures._assistant("a", "p", "m", {"type": "text", "text": "x"}), 0, 1)
    assert not reply.turn_start and reply.snippet == ""
