
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from src.cplugs.reviewboard import document
from src.cplugs.reviewboard.layers import shell
from src.cplugs.reviewboard.requests import ReviseBody
from tests.python.cplugs.reviewboard.boards import SIDECAR
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_on, task_manager_store, make_env
from tests.python.cplugs.reviewboard.layer_fixtures import OPTIONS, QUESTIONS, ROWS, layer_sidecar
from tests.python.cplugs.reviewboard.test_publish import ANCHORS, create_body

Edit = Callable[[Dict[str, Any]], None]


def item(layer: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    return next(i for i in layer.get("items", layer.get("rows")) if i["id"] == item_id)


@pytest.mark.parametrize("layer", [QUESTIONS, ROWS], ids=["questions", "rows"])
def test_each_layer_kind_round_trips_byte_for_byte(layer: Dict[str, Any]) -> None:
    raw = layer_sidecar(layer)
    text = document.canonical_text(document.parse_sidecar(raw))
    assert json.loads(text) == raw
    assert document.canonical_text(document.parse_sidecar(json.loads(text))) == text
    if layer is QUESTIONS:
        assert '"min": 1,' in text and '"min": 1.0' not in text and '"default": 2.5' in text


def test_absent_layer_fields_stay_absent_and_old_sidecars_gain_none() -> None:
    assert "layer" not in document.canonical_text(document.parse_sidecar(SIDECAR))
    bare = layer_sidecar({"kind": "questions", "v": 1, "title": "t", "placement": "inline", "items": [{"id": "q", "label": "q", "kind": "yesno"}]})
    kept = json.loads(document.canonical_text(document.parse_sidecar(bare)))["revisions"][0]["layer"]
    assert kept == bare["revisions"][0]["layer"]


def mutated(layer: Dict[str, Any], edit: Edit, **revision: Any) -> Dict[str, Any]:
    copied = copy.deepcopy(layer)
    edit(copied)
    return layer_sidecar(copied, **revision)


REFUSALS = [
    ("unknown kind", QUESTIONS, lambda l: l["items"][0].update(kind="slider"), "kind"),
    ("unknown layer kind", QUESTIONS, lambda l: l.update(kind="grid"), "kind"),
    ("unknown field", QUESTIONS, lambda l: l["items"][0].update(color="red"), "color"),
    ("duplicate item id", QUESTIONS, lambda l: l["items"][1].update(id="keep-rail"), "an item id is used twice"),
    ("duplicate option id", QUESTIONS, lambda l: item(l, "density")["options"].append({"id": "a", "label": "again"}), "an option id is used twice"),
    ("undeclared anchor", QUESTIONS, lambda l: item(l, "keep-rail").update(anchor="nowhere"), "anchor nowhere is not declared"),
    ("choice default not an option", QUESTIONS, lambda l: item(l, "density").update(default="z"), "not one of its options"),
    ("multi default over max", QUESTIONS, lambda l: item(l, "panels").update(default=["a", "b", "c"]), "outside min and max"),
    ("multi min above max", QUESTIONS, lambda l: item(l, "panels").update(min=3, max=2, default=None), "min is above max"),
    ("rank default not a permutation", QUESTIONS, lambda l: item(l, "order").update(default=["a", "b"]), "lists every option once"),
    ("number default out of range", QUESTIONS, lambda l: item(l, "size").update(default=99), "outside min and max"),
    ("number default is a bool", QUESTIONS, lambda l: item(l, "size").update(default=True), "default"),
    ("slider without bounds", QUESTIONS, lambda l: item(l, "size").update(max=None, default=None), "a slider needs both"),
    ("date that is no day", QUESTIONS, lambda l: item(l, "due").update(default="2026-02-31"), "not a calendar day"),
    ("date default out of range", QUESTIONS, lambda l: item(l, "due").update(default="2027-01-01"), "outside min and max"),
    ("version not 1", QUESTIONS, lambda l: l.update(v=2), "v"),
    ("no items", QUESTIONS, lambda l: l.update(items=[]), "items"),
    ("61 items", QUESTIONS, lambda l: l.update(items=[{"id": f"q{i}", "label": "q", "kind": "yesno"} for i in range(61)]), "items"),
    ("13 options on a choice", QUESTIONS, lambda l: item(l, "density").update(options=[{"id": f"o{i}", "label": "o"} for i in range(13)], default=None), "options"),
    ("label over 300", QUESTIONS, lambda l: l["items"][0].update(label="x" * 301), "label"),
    ("duplicate row id", ROWS, lambda l: l["rows"][1].update(id="aw-001"), "a row id is used twice"),
    ("undeclared row anchor", ROWS, lambda l: item(l, "aw-001").update(anchor="nowhere"), "anchor nowhere is not declared"),
    ("row with no choices", ROWS, lambda l: l.pop("choices"), "no choices"),
    ("suggest not a choice", ROWS, lambda l: item(l, "aw-001").update(suggest="keep"), "not one of its choices"),
    ("default not a choice", ROWS, lambda l: item(l, "aw-002").update(default="ok"), "pick-one row carries one of its choice ids"),
    ("list default on pick one", ROWS, lambda l: item(l, "aw-002").update(default=["keep"]), "pick-one row carries one"),
    ("string default on pick several", ROWS, lambda l: (l.update(pick="several"), item(l, "aw-002").update(default="keep")), "pick-several row carries a list"),
    ("bad tone", ROWS, lambda l: l["choices"][0].update(tone="red"), "tone"),
    ("9 lines on a row", ROWS, lambda l: item(l, "aw-001").update(lines=[{"label": "l", "text": "t"}] * 9), "lines"),
    ("201 rows", ROWS, lambda l: l.update(rows=[{"id": f"r{i}", "title": "t"} for i in range(201)]), "rows"),
    ("13 layer choices", ROWS, lambda l: l.update(choices=[{"id": f"c{i}", "label": "c"} for i in range(13)]), "choices"),
]


@pytest.mark.parametrize("name,layer,edit,message", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_a_malformed_layer_is_refused_naming_the_field(name: str, layer: Dict[str, Any], edit: Edit, message: str) -> None:
    with pytest.raises(document.SidecarInvalid, match=message):
        document.parse_sidecar(mutated(layer, edit))


def test_a_layer_revision_is_payload_mode_and_carries_no_prompts() -> None:
    with pytest.raises(document.SidecarInvalid, match="a layer revision is payload_mode"):
        document.parse_sidecar(mutated(QUESTIONS, lambda l: None, payload_mode=None))
    with pytest.raises(document.SidecarInvalid, match="carries no prompts"):
        document.parse_sidecar(mutated(QUESTIONS, lambda l: None, prompts=SIDECAR["revisions"][0]["prompts"]))


def test_a_valid_anchor_declared_by_the_revision_is_accepted() -> None:
    raw = mutated(QUESTIONS, lambda l: item(l, "keep-rail").update(anchor="buttons"))
    assert document.parse_sidecar(raw).revisions[0].layer.items[0].anchor == "buttons"


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path)
    task_manager_on(env, monkeypatch)
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as client:
        yield env, client
    board_port.unregister()


def layer_body(item_id: int, layer: Dict[str, Any], **over: Any) -> Dict[str, Any]:
    body = create_body(item_id, prompts=[], anchors=ANCHORS, layer=layer)
    body.pop("html")
    return {**body, **over}


def new_task(env) -> int:
    return task_manager_store(env).add("all", "layer board", actor="claude", title="Layer board")["id"]


@pytest.mark.parametrize("layer", [QUESTIONS, ROWS], ids=["questions", "rows"])
def test_a_layer_board_with_no_page_gets_a_generated_shell(world, layer: Dict[str, Any]) -> None:
    env, client = world
    made = client.post(f"{BASE}/boards", json=layer_body(new_task(env), layer))
    assert made.status_code == 200, made.text
    folder = env.board(made.json()["slug"])
    sidecar = json.loads((folder / "sidecar.json").read_text())
    row = sidecar["revisions"][0]
    assert row["payload_mode"] is True and row["layer"] == layer and row["prompts"] == []
    page = (folder / "r001.html").read_text()
    assert page == shell.shell_page(layer["title"]) and "data-rb-layer-root" in page and "<script" not in page
    assert document.parse_sidecar(sidecar).revisions[0].layer.kind == layer["kind"]


def test_a_layer_board_may_bring_its_own_page(world) -> None:
    env, client = world
    body = layer_body(new_task(env), QUESTIONS, html="<p data-rb-anchor='send'>mine</p>")
    made = client.post(f"{BASE}/boards", json=body)
    assert made.status_code == 200, made.text
    assert (env.board(made.json()["slug"]) / "r001.html").read_text() == "<p data-rb-anchor='send'>mine</p>"


def test_the_canvas_alias_is_payload_mode_with_no_stored_layer(world) -> None:
    env, client = world
    made = client.post(f"{BASE}/boards", json=create_body(new_task(env), prompts=[], layer={"kind": "canvas"}))
    assert made.status_code == 200, made.text
    row = json.loads((env.board(made.json()["slug"]) / "sidecar.json").read_text())["revisions"][0]
    assert row["payload_mode"] is True and "layer" not in row


@pytest.mark.parametrize("name,over", [
    ("layer plus prompts", {"prompts": SIDECAR["revisions"][0]["prompts"]}),
    ("layer with payload_mode false", {"payload_mode": False}),
    ("unknown layer kind", {"layer": {"kind": "wizard"}}),
    ("no page and no layer", {"layer": None}),
    ("canvas without a page", {"layer": {"kind": "canvas"}}),
    ("an undeclared anchor", {"anchors": []}),
], ids=lambda v: v if isinstance(v, str) else "")
def test_a_bad_layer_request_is_refused_422_and_writes_nothing(world, name: str, over: Dict[str, Any]) -> None:
    env, client = world
    body = layer_body(new_task(env), QUESTIONS)
    body = {**body, **over}
    if name == "no page and no layer":
        body.pop("layer")
    if name == "layer plus prompts":
        body["anchors"] = ANCHORS
    before = sorted(p.name for p in env.root.rglob("*"))
    refused = client.post(f"{BASE}/boards", json=body)
    assert refused.status_code == 422, (name, refused.text)
    assert sorted(p.name for p in env.root.rglob("*")) == before


def test_a_layer_revision_is_added_to_an_existing_board(world) -> None:
    env, client = world
    made = client.post(f"{BASE}/boards", json=create_body(new_task(env), prompts=[], anchors=ANCHORS)).json()
    added = client.post(f"{BASE}/boards/{made['slug']}/revisions", json={"summary": "r2 as a layer", "layer": QUESTIONS, "anchors": ANCHORS})
    assert added.status_code == 200, added.text
    rows = json.loads((env.board(made["slug"]) / "sidecar.json").read_text())["revisions"]
    assert "layer" not in rows[0] and rows[1]["layer"] == QUESTIONS and rows[1]["payload_mode"] is True


def test_the_revise_body_needs_a_page_or_a_layer() -> None:
    with pytest.raises(ValidationError, match="html is required"):
        ReviseBody(summary="s")
    assert ReviseBody(summary="s", layer=QUESTIONS).html is None
    with pytest.raises(ValidationError, match="carries no prompts"):
        ReviseBody(summary="s", layer=QUESTIONS, prompts=SIDECAR["revisions"][0]["prompts"])


def test_the_published_json_schema_names_the_layer() -> None:
    from src.cplugs.reviewboard.cli.emit_schema import schema_text
    text = schema_text()
    assert '"QuestionsLayer"' in text and '"RowsLayer"' in text and OPTIONS


def test_the_shell_page_prints_no_title_of_its_own() -> None:
    page = shell.shell_page("restart picker review")
    assert page.count("restart picker review") == 1 and "<header" not in page


def test_a_closed_note_cannot_be_forced_open_by_a_control_display() -> None:
    css = (Path(__file__).resolve().parents[4] / "src/cplugs/reviewboard/frame/layer.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\][^{]*\{\s*display:\s*none\s*!important", css)
    assert css.count("max-width: var(--rbl-field-max)") >= 3


@pytest.mark.parametrize("width,ok", [(None, True), (480, True), (2400, True), (479, False), (2401, False), (0, False), ("wide", False)])
def test_a_canvas_max_width_is_stored_when_in_range_and_refused_otherwise(width, ok) -> None:
    from src.cplugs.reviewboard.requests import RevisionBody
    from src.cplugs.reviewboard.revisions import _revision
    from datetime import datetime, timezone

    args = {"summary": "s", "html": "<p>x</p>", "viewport": 520}
    if width is not None:
        args["max_width"] = width
    if not ok:
        with pytest.raises(ValidationError):
            RevisionBody(**args)
        return
    row, _ = _revision(RevisionBody(**args), 1, 520, datetime.now(timezone.utc), {"actor": "agent"})
    assert row.get("max_width") == width
    assert ("max_width" in row) == (width is not None)
