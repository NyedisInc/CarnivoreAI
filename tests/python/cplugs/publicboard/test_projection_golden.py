
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.python.cplugs.publicboard.read_harness import edge, get, leaky_strings, mint_token

TOP_KEYS = {"title", "revision", "summary", "viewport", "max_width", "views", "prompts", "anchors", "layer", "expires_at"}


def test_the_board_answer_has_exactly_the_allowed_keys(read_env, store) -> None:
    got = get(edge(), "/api/board", mint_token(store))
    assert got.status == 200, got.body
    body = got.json()
    assert set(body) == TOP_KEYS
    assert [set(v) for v in body["views"]] == [{"id", "label", "frame"}]
    assert {frozenset(p) for p in body["prompts"]} == {frozenset({"id", "kind", "label", "anchor", "options"})}
    assert set(body["prompts"][0]["options"][0]) == {"id", "label"}
    assert set(body["anchors"][0]) == {"id", "label"}
    assert body["title"] == "bottom bar" and body["revision"] == "r1" and body["viewport"] == 320


def test_nothing_of_the_private_side_is_in_any_answer(read_env, store, folder: Path) -> None:
    (folder / "attachments").mkdir()
    (folder / "attachments" / "private-notes.txt").write_text("owner only")
    app = edge()
    got = get(app, "/api/board", mint_token(store))
    frame = get(app, got.json()["views"][0]["frame"])
    assert frame.status == 200
    for answer in (got, frame):
        text = answer.body.decode()
        for leaked in leaky_strings() + ["private-notes", "owner only"]:
            assert leaked not in text, leaked
    assert re.fullmatch(r"/f/[A-Za-z0-9_.-]+", got.json()["views"][0]["frame"])


def test_a_visitor_reaches_only_the_board_the_link_names(read_env, store, folder: Path) -> None:
    token = mint_token(store)
    app = edge()
    for path in ("/api/board/20261014-leaky", "/boards/20261013-bottom-bar", "/attachments/private-notes.txt", "/r001.html", "/sidecar.json",
                 "/api/v1/cplugs/publicboard/links", "/api/v1/cplugs/reviewboard/boards", "/links"):
        got = get(app, path, token)
        assert got.status == 404 and got.body == b"", path


def test_every_row_the_projection_names_is_a_field_of_the_port(read_env) -> None:
    from src.cplugs.sdk.board_public import port

    shown = port().public_revision("20261013-bottom-bar", "r1", "main")
    assert set(shown.projection) == TOP_KEYS - {"expires_at"}
    assert shown.page is not None and b"data-rb-anchor" in shown.page
    assert shown.revision == "r1" and shown.latest == "r1"


@pytest.mark.parametrize("revision,view", [("r9", None), ("r1", "nope"), ("draft", None)])
def test_the_port_refuses_what_is_not_there(read_env, revision: str, view: Any) -> None:
    from src.cplugs.sdk.board_public import PublicBoardMissing, port

    with pytest.raises(PublicBoardMissing):
        port().public_revision("20261013-bottom-bar", revision, view)
