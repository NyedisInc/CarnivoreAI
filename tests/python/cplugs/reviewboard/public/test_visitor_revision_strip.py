
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.cplugs.reviewboard.public import minting
from tests.python.cplugs.reviewboard.public.read_harness import add_revision, edge, get, mint_token

SECOND = b"<!doctype html><title>bar</title><main>second</main>"
THIRD = b"<!doctype html><title>bar</title><main>third</main>"
ANSWER = [{"prompt": "layout", "options": ["b"]}]


def vkey(n: int) -> str:
    return f"{n:04d}" + "k" * 18


def board(token: str, visitor: Optional[str] = None, revision: Optional[str] = None) -> Any:
    extra = tuple(h for h in (("Carnivore-Visitor", visitor) if visitor else None, ("Carnivore-Revision", revision) if revision else None) if h)
    return get(edge(), "/api/board", token, extra=extra)


def autosave(token: str, visitor: str, revision: str, answers: List[Dict[str, Any]]) -> int:
    return get(edge(), "/api/draft", token, method="POST", body=json.dumps({"revision": revision, "answers": answers}).encode(),
               extra=(("Carnivore-Visitor", visitor),)).status


def served(token: str, folder: Any) -> None:
    board(token)
    add_revision(folder, SECOND)
    board(token)
    add_revision(folder, THIRD)
    board(token)


def test_a_follow_link_lists_every_revision_it_served_and_marks_only_my_answers(read_env, store, folder) -> None:
    token = mint_token(store, mode="follow")
    served(token, folder)
    assert autosave(token, vkey(1), "r1", ANSWER) == 200
    assert autosave(token, vkey(2), "r2", ANSWER) == 200
    mine = board(token, vkey(1)).json()
    assert mine["revision"] == "r3" and mine["revisions"] == [
        {"revision": "r1", "answered": True}, {"revision": "r2", "answered": False}, {"revision": "r3", "answered": False}]
    other = board(token, vkey(2)).json()
    assert [r["answered"] for r in other["revisions"]] == [False, True, False]
    assert [r["answered"] for r in board(token).json()["revisions"]] == [False, False, False]
    assert [r["answered"] for r in board(token, vkey(3)).json()["revisions"]] == [False, False, False]


def test_a_pinned_link_lists_its_one_revision(read_env, store, folder) -> None:
    token = mint_token(store)
    add_revision(folder, SECOND)
    assert board(token).json()["revisions"] == [{"revision": "r1", "answered": False}]


def test_naming_a_served_revision_shows_it_with_my_answers_only(read_env, store, folder) -> None:
    token = mint_token(store, mode="follow")
    served(token, folder)
    assert autosave(token, vkey(1), "r1", ANSWER) == 200
    assert autosave(token, vkey(2), "r1", [{"prompt": "padding", "checked": True}]) == 200
    review = board(token, vkey(1), "r1").json()
    assert review["revision"] == "r1" and review["draft"] == {"body": {"answers": ANSWER}}
    assert board(token, vkey(2), "r1").json()["draft"] == {"body": {"answers": [{"prompt": "padding", "checked": True}]}}
    assert board(token, vkey(3), "r1").json()["draft"] is None
    assert board(token, None, "r1").json()["draft"] is None
    frame = get(edge(), review["views"][0]["frame"])
    assert frame.status == 200 and b"<main>second</main>" not in frame.body


def test_a_revision_the_link_never_served_is_ignored_and_its_existence_not_told(read_env, store, folder) -> None:
    pinned = mint_token(store)
    add_revision(folder, SECOND)
    add_revision(folder, THIRD)
    for ask in ("r2", "r3", "r99", "nonsense", "../x"):
        got = board(pinned, None, ask)
        assert got.status == 200 and got.json()["revision"] == "r1" and got.json()["revisions"] == [{"revision": "r1", "answered": False}], ask


def test_a_past_revision_that_now_holds_a_credential_is_not_served(read_env, store, folder, monkeypatch) -> None:
    token = mint_token(store, mode="follow")
    served(token, folder)
    real = minting.scan_texts
    seen: List[str] = []

    def flagged(texts: Any) -> Any:
        seen.append("call")
        return {"leak": 1} if not any("second" in t or "third" in t for t in texts) else real(texts)

    monkeypatch.setattr(minting, "scan_texts", flagged)
    assert board(token, None, "r1").json()["revision"] == "r3"
    assert seen
