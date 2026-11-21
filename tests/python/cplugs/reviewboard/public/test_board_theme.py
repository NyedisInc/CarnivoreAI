
from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from tests.python.cplugs.reviewboard.public.read_harness import edge, get, mint_token
from tests.python.cplugs.reviewboard.boards import SIDECAR

SLUG = SIDECAR["board"]["slug"]
LOOK = f"/api/v1/cplugs/reviewboard/boards/{SLUG}/look"
LINK_PALETTE = {"--oc-orange": "rgb(1, 2, 3)"}
BOARD_PALETTE = {"--oc-orange": "rgb(250, 250, 250)", "--oc-ground-page": "rgb(255, 255, 255)"}


@pytest.fixture
def owner(read_env: Any) -> Iterator[TestClient]:
    read_env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(read_env.app) as client:
        yield client
    read_env.app.dependency_overrides.clear()


def visitor_theme(token: str) -> Any:
    return get(edge(), "/api/board", token).json()["theme"]


def test_the_choice_is_kept_per_board_and_cleared_to_follow_my_theme(read_env, owner) -> None:
    assert owner.get(LOOK).json() == {"look": None}
    saved = owner.put(LOOK, json={"theme": "carnivore-light", "palette": BOARD_PALETTE})
    assert saved.status_code == 200 and saved.json() == {"look": {"theme": "carnivore-light", "palette": BOARD_PALETTE}}
    assert owner.get(LOOK).json()["look"]["theme"] == "carnivore-light"
    assert owner.put(LOOK, json={"theme": None, "palette": None}).json() == {"look": None}
    assert owner.get(LOOK).json() == {"look": None}


def test_a_bad_body_or_slug_is_refused(read_env, owner) -> None:
    assert owner.put(LOOK, json={"theme": "x", "palette": {"--oc-a": 3}}).status_code == 422
    assert owner.put(LOOK, json={"theme": 7, "palette": {}}).status_code == 422
    assert owner.put(LOOK, json={"theme": "x", "palette": {"color": "red"}}).status_code == 422
    assert owner.put("/api/v1/cplugs/reviewboard/boards/not-a-slug/look", json={"theme": None, "palette": None}).status_code in (404, 422)


def test_visitors_get_the_live_board_theme_and_it_wins_over_the_link_s(read_env, store, owner) -> None:
    from asyncio import run
    from types import SimpleNamespace
    from src.plugins.reviewboard.public import minting
    token = run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", "pinned", theme=LINK_PALETTE))["token"]
    assert visitor_theme(token) == LINK_PALETTE
    owner.put(LOOK, json={"theme": "carnivore-light", "palette": BOARD_PALETTE})
    assert visitor_theme(token) == BOARD_PALETTE
    owner.put(LOOK, json={"theme": None, "palette": None})
    assert visitor_theme(token) == LINK_PALETTE


def test_a_link_with_no_captured_theme_still_wears_the_boards(read_env, store, owner) -> None:
    token = mint_token(store)
    assert visitor_theme(token) is None
    owner.put(LOOK, json={"theme": "carnivore-light", "palette": BOARD_PALETTE})
    assert visitor_theme(token) == BOARD_PALETTE


def test_an_unsafe_value_in_a_stored_palette_never_reaches_a_visitor(read_env, store, owner) -> None:
    owner.put(LOOK, json={"theme": "x", "palette": {"--oc-orange": "red; background: url(https://evil)", "--oc-cyan": "rgb(1, 2, 3)"}})
    assert visitor_theme(mint_token(store)) == {"--oc-cyan": "rgb(1, 2, 3)"}


def test_an_oversized_stored_palette_falls_back_to_the_link_s_and_never_fails_the_read(read_env, store, owner) -> None:
    import json
    from asyncio import run
    from types import SimpleNamespace
    from src.plugins.reviewboard.public import minting
    token = run(minting.mint_link(SimpleNamespace(storage=store), SLUG, "1d", "pinned", theme=LINK_PALETTE))["token"]
    owner.put(LOOK, json={"theme": "x", "palette": BOARD_PALETTE})
    [path] = list(read_env.host.storage("reviewboard").path.glob(f"looks/{SLUG}.json"))
    path.write_text(json.dumps({"theme": "x", "palette": {f"--oc-n{i}": "red" for i in range(5000)}}), encoding="utf-8")
    assert get(edge(), "/api/board", token).status == 200
    assert visitor_theme(token) == LINK_PALETTE
    assert owner.get(LOOK).json() == {"look": None}


def test_the_reader_itself_drops_an_unusable_palette_whatever_port_handed_it_over() -> None:
    from src.plugins.reviewboard.public.read import _board_palette
    assert _board_palette({f"--oc-n{i}": "red" for i in range(5000)}) is None
    assert _board_palette({"--oc-a": "red"}) == {"--oc-a": "red"} and _board_palette(None) is None
