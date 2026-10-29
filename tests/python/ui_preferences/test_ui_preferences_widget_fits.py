
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.preferences_routes import router as preferences_router
from src.core.ui_preferences_store import UiPreferencesStore
from src.core.widget_fits import load_fits, widget_for_slot
from src.core.widget_fits.rules import GRID_SIZE_NAMES, FitsCatalogError, parse_fits


def grid(*slots: str, size: int = 320, kind: str = "px") -> dict:
    share = 1 / len(slots)
    return {
        "v": 6,
        "rows": [{"id": "r1", "kind": kind, "size": size, "slots": [{"id": one, "fr": share} for one in slots]}],
        "hidden": [],
        "heroCollapsed": False,
    }


def home(layout: dict) -> dict:
    return {"v": 2, "boards": [{"id": "home", "name": "home", "layout": layout}], "analytics_seed": 0}


def terminal(layout: dict) -> dict:
    return {"v": 1, "sessions": {"s1#1": {"layout": layout, "groups": {}}}}


@pytest.fixture
def client(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.ui_preferences_store = UiPreferencesStore(lambda: path)
    app.state.connection_manager = None
    with TestClient(app) as test_client:
        yield test_client


def patch(client: TestClient, field: str, value: dict):
    return client.patch("/api/v1/preferences", json={"changes": {field: value}, "expected_revision": None})


def test_the_shipped_contract_covers_every_widget_and_names_no_zone():
    fits = load_fits()
    assert len(fits) >= 14
    assert all(fit.sizes and fit.any_size for fit in fits.values())
    assert all(name in GRID_SIZE_NAMES for fit in fits.values() for name in fit.sizes)
    assert not hasattr(fits["core.projects"], "zones")
    assert widget_for_slot("analytics:00000000-0000-0000-0000-000000000000") == "core.analytics"


def test_a_home_widget_on_the_terminal_page_commits(client):
    assert patch(client, "terminal_layouts", terminal(grid("terminal:@primary", "projects"))).status_code == 200


def test_any_widget_goes_in_the_drawer_area_and_the_glance_area(client):
    zone = {"v": 1, "items": [{"widget": "core.ledger"}, {"widget": "core.notes"}],
            "glance": [{"id": "g-notes1", "widget": "core.notes"}]}
    assert patch(client, "drawer_zone", zone).status_code == 200


def test_a_malformed_write_is_still_refused(client):
    assert patch(client, "drawer_zone", {"v": 1, "items": "notes"}).status_code == 400


def test_named_sizes_read_back_and_a_retired_key_is_refused_by_name():
    row = {"id": "acme.clock", "fits": {"sizes": ["small", "wide"]}}
    parsed = parse_fits({"widgets": [row]})["acme.clock"]
    assert parsed.sizes == ("small", "wide") and parsed.any_size is False
    assert parse_fits({"widgets": [{"id": "acme.big", "fits": {"sizes": ["full"], "anySize": True}}]})["acme.big"].any_size
    for retired in ("zones", "suggested", "tested", "max", "allowed"):
        with pytest.raises(FitsCatalogError, match=f"fits.{retired} is retired"):
            parse_fits({"widgets": [{"id": "acme.clock", "fits": {"sizes": ["small"], retired: []}}]})
    with pytest.raises(FitsCatalogError, match="repeats"):
        parse_fits({"widgets": [{"id": "acme.clock", "fits": {"sizes": ["wide", "wide"]}}]})
    with pytest.raises(FitsCatalogError, match="not a size name"):
        parse_fits({"widgets": [{"id": "acme.clock", "fits": {"sizes": ["2x2"]}}]})
    with pytest.raises(FitsCatalogError, match="not a list of size names"):
        parse_fits({"widgets": [{"id": "acme.clock", "fits": {}}]})
    with pytest.raises(FitsCatalogError, match="declares no fits"):
        parse_fits({"widgets": [{"id": "acme.plain"}]})
    with pytest.raises(FitsCatalogError, match="anySize"):
        parse_fits({"widgets": [{"id": "acme.clock", "fits": {"sizes": ["small"], "anySize": "yes"}}]})


def test_the_server_names_the_same_sizes_as_the_browser():
    source = (Path(__file__).resolve().parents[3] / "web/src/opscenter/widgets/named-sizes.ts").read_text()
    declared = source.split("GRID_SIZE_NAMES = [", 1)[1].split("]", 1)[0]
    assert tuple(name.strip().strip("'") for name in declared.split(",")) == GRID_SIZE_NAMES


def _fits_doc(instancing: str, **extra: object) -> dict:
    return {"widgets": [{"id": "acme.clock", "instancing": instancing, "fits": {"sizes": ["small"], **extra}}]}


def test_every_shipped_max_per_surface_is_valid() -> None:
    rows = json.loads((Path(__file__).resolve().parents[3] / "src" / "data" / "widgets.json").read_text())["widgets"]
    fits = load_fits()
    for row in rows:
        limit = fits[row["id"]].max_per_surface
        assert limit is None or (isinstance(limit, int) and 1 <= limit <= 12), row["id"]
        if row["instancing"] == "singleton":
            assert limit == 1, row["id"]


@pytest.mark.parametrize("bad", [0, -1, 13, 1.5, "2", True])
def test_max_per_surface_must_be_a_whole_number_in_range(bad: object) -> None:
    with pytest.raises(FitsCatalogError, match="max_per_surface"):
        parse_fits(_fits_doc("per-target", max_per_surface=bad))


def test_a_singleton_may_only_declare_one_and_absent_is_unlimited() -> None:
    with pytest.raises(FitsCatalogError, match="singleton"):
        parse_fits(_fits_doc("singleton", max_per_surface=2))
    assert parse_fits(_fits_doc("per-target"))["acme.clock"].max_per_surface is None
    assert parse_fits(_fits_doc("per-target", max_per_surface=3))["acme.clock"].max_per_surface == 3
