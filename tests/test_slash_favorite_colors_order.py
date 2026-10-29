from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fco_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fco_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.auth_routes import router as auth_router
from src.config import settings
from src.core import slash_command_labels, slash_favorites

DEFAULTS = slash_command_labels.DEFAULT_COMMON_COMMANDS
LIST_URL = "/api/v1/config/common-commands"
FAVORITE_URL = "/api/v1/config/common-commands/favorite"
COLOR_URL = "/api/v1/config/common-commands/color"
ORDER_URL = "/api/v1/config/common-commands/order"


@pytest.fixture()
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path))
    settings._auth_config_cache = None
    yield path
    settings._auth_config_cache = None


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _disk(path: Path) -> dict:
    return json.loads(path.read_text())


def _seed(path: Path, **keys) -> None:
    data = _disk(path)
    data.update(keys)
    path.write_text(json.dumps(data))


def _colors(body: dict) -> dict:
    return {d["command"]: d["color"] for d in body["command_details"]}



def test_every_favorite_carries_a_color_field_and_none_is_null(client, config_path):
    body = client.get(LIST_URL).json()
    assert body["command_details"], "the defaults must render"
    assert all(d["color"] is None for d in body["command_details"])


def test_the_swatch_set_is_the_five_token_names_and_never_the_accent():
    assert slash_favorites.FAVORITE_COLORS == (
        "yellow", "green", "cyan", "violet", "coral",
    )


def test_setting_a_color_persists_in_its_own_key(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff"])
    resp = client.post(COLOR_URL, json={"command": "/diff", "color": "green"})
    assert resp.status_code == 200, resp.text
    assert _colors(resp.json()) == {"/clear": None, "/diff": "green"}
    disk = _disk(config_path)
    assert disk[slash_favorites.COLORS_KEY] == {"/diff": "green"}
    assert disk[slash_favorites.FAVORITES_KEY] == ["/clear", "/diff"]


def test_a_fresh_get_agrees_with_the_color_response(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"])
    posted = client.post(COLOR_URL, json={"command": "clear", "color": "cyan"}).json()
    assert client.get(LIST_URL).json() == posted


def test_null_clears_the_color_and_drops_an_empty_map(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"],
          slash_favorite_colors={"/clear": "violet"})
    resp = client.post(COLOR_URL, json={"command": "/clear", "color": None})
    assert resp.status_code == 200, resp.text
    assert _colors(resp.json()) == {"/clear": None}
    assert slash_favorites.COLORS_KEY not in _disk(config_path)


def test_coloring_a_non_favorite_is_a_409_with_the_current_row(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"])
    before = config_path.read_text()
    resp = client.post(COLOR_URL, json={"command": "/diff", "color": "green"})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "favorites_stale"
    assert detail["current"]["commands"] == ["/clear"]
    assert config_path.read_text() == before


def test_an_unknown_color_is_refused_and_writes_nothing(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"])
    before = config_path.read_text()
    resp = client.post(COLOR_URL, json={"command": "/clear", "color": "#ff0000"})
    assert resp.status_code == 422
    assert config_path.read_text() == before


def test_the_color_field_is_required_so_a_typo_cannot_clear(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"])
    resp = client.post(COLOR_URL, json={"command": "/clear", "colour": "green"})
    assert resp.status_code == 422


def test_coloring_a_default_materializes_the_defaults(client, config_path):
    resp = client.post(COLOR_URL, json={"command": DEFAULTS[0], "color": "yellow"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["defaulted"] is False
    assert body["commands"] == DEFAULTS
    assert _disk(config_path)[slash_favorites.FAVORITES_KEY] == DEFAULTS


def test_unstarring_drops_the_color(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff"],
          slash_favorite_colors={"/clear": "green", "/diff": "coral"})
    resp = client.post(FAVORITE_URL, json={"command": "/diff", "favorite": False})
    assert resp.status_code == 200, resp.text
    assert _disk(config_path)[slash_favorites.COLORS_KEY] == {"/clear": "green"}
    again = client.post(FAVORITE_URL, json={"command": "/diff", "favorite": True}).json()
    assert _colors(again)["/diff"] is None


def test_a_hand_edited_bad_value_reads_as_no_color(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff"],
          slash_favorite_colors={"/clear": "#123456", "/diff": "green", "/gone": "cyan"})
    assert _colors(client.get(LIST_URL).json()) == {"/clear": None, "/diff": "green"}


def test_a_non_dict_color_map_degrades_to_none(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"], slash_favorite_colors=["x"])
    assert _colors(client.get(LIST_URL).json()) == {"/clear": None}



def test_reorder_persists_and_keeps_each_entry_form(client, config_path):
    hand = {"command": "/deploy", "description": "ship it"}
    _seed(config_path, common_slash_commands=["/clear", hand, "/diff"],
          slash_favorite_colors={"/deploy": "yellow"})
    resp = client.post(ORDER_URL, json={"commands": ["/diff", "deploy", "/clear"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["commands"] == ["/diff", "/deploy", "/clear"]
    assert _colors(body)["/deploy"] == "yellow"
    assert _disk(config_path)[slash_favorites.FAVORITES_KEY] == ["/diff", hand, "/clear"]


def test_reorder_from_a_stale_set_is_a_409_and_writes_nothing(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff", "/review"])
    before = config_path.read_text()
    resp = client.post(ORDER_URL, json={"commands": ["/diff", "/clear"]})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "favorites_stale"
    assert detail["current"]["commands"] == ["/clear", "/diff", "/review"]
    assert config_path.read_text() == before


def test_reorder_naming_a_non_favorite_is_a_409(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff"])
    resp = client.post(ORDER_URL, json={"commands": ["/diff", "/review"]})
    assert resp.status_code == 409


def test_reorder_with_a_duplicate_is_a_409(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff"])
    resp = client.post(ORDER_URL, json={"commands": ["/diff", "/diff", "/clear"]})
    assert resp.status_code == 409


def test_reorder_of_the_defaults_materializes_them(client, config_path):
    wanted = list(reversed(DEFAULTS))
    resp = client.post(ORDER_URL, json={"commands": wanted})
    assert resp.status_code == 200, resp.text
    assert resp.json()["commands"] == wanted
    assert resp.json()["defaulted"] is False
    assert _disk(config_path)[slash_favorites.FAVORITES_KEY] == wanted


def test_reorder_invalidates_the_settings_cache(client, config_path):
    _seed(config_path, common_slash_commands=["/clear", "/diff"])
    settings._auth_config_cache = object()
    client.post(ORDER_URL, json={"commands": ["/diff", "/clear"]})
    assert settings._auth_config_cache is None


def test_color_invalidates_the_settings_cache(client, config_path):
    _seed(config_path, common_slash_commands=["/clear"])
    settings._auth_config_cache = object()
    client.post(COLOR_URL, json={"command": "/clear", "color": "green"})
    assert settings._auth_config_cache is None



def test_reorder_core_refuses_a_mismatch():
    with pytest.raises(slash_favorites.FavoritesStale):
        slash_favorites.reorder(["/clear", "/diff"], True, ["/clear"])


def test_reorder_core_is_a_permutation():
    assert slash_favorites.reorder(["/a", "/b", "/c"], True, ["/c", "/a", "/b"]) == ["/c", "/a", "/b"]


def test_colors_for_filters_to_current_favorites_and_known_ids():
    raw = {"/a": "green", "/b": "nope", "/c": "cyan", 7: "green"}
    assert slash_favorites.colors_for(raw, ["/a", "/b"]) == {"/a": "green"}


def test_the_request_model_accepts_exactly_the_core_swatch_set():
    import typing

    from src.models.agents import ReorderFavoritesRequest, SetFavoriteColorRequest

    annotation = SetFavoriteColorRequest.model_fields["color"].annotation
    literal = next(a for a in typing.get_args(annotation) if a is not type(None))
    assert typing.get_args(literal) == slash_favorites.FAVORITE_COLORS
    bound = [m for m in ReorderFavoritesRequest.model_fields["commands"].metadata
             if hasattr(m, "max_length")]
    assert bound and bound[0].max_length == slash_favorites.MAX_FAVORITES
