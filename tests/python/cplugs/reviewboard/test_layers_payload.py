
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Dict

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from src.cplugs.reviewboard.layers import payload as layer_payload
from tests.python.cplugs.reviewboard.harness import BASE, huddle_on, huddle_store, make_env
from tests.python.cplugs.reviewboard.layer_fixtures import QUESTIONS, ROWS
from tests.python.cplugs.reviewboard.test_layers_format import layer_body
from tests.python.cplugs.reviewboard.test_publish import create_body

GOOD_Q: Dict[str, Any] = {"layer": "questions", "v": 1,
                          "values": {"keep-rail": True, "dense": False, "density": "a", "panels": ["a", "c"], "order": ["b", "c", "a"], "name": "n", "why": "w",
                                     "size": 3, "due": "2026-11-02"},
                          "notes": {"keep-rail": "only on desktop"}}
GOOD_R: Dict[str, Any] = {"layer": "rows", "v": 1, "values": {"aw-001": "later", "aw-002": "drop"}, "notes": {"aw-002": "ask the team first"}}


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path)
    huddle_on(env, monkeypatch)
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as client:
        yield env, client
    board_port.unregister()


def make_board(world, layer: Dict[str, Any] | None) -> str:
    env, client = world
    item = huddle_store(env).add("all", "layer board", actor="claude", title="Layer board")["id"]
    body = layer_body(item, layer, anchors=[{"id": "send", "label": "send"}]) if layer else create_body(item, prompts=[], anchors=[], payload_mode=True)
    made = client.post(f"{BASE}/boards", json=body)
    assert made.status_code == 200, made.text
    return made.json()["slug"]


def doors(client, slug: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"draft": client.put(f"{BASE}/boards/{slug}/payload-draft", json={"revision": "r1", "payload": payload}),
            "save": client.post(f"{BASE}/boards/{slug}/saves", json={"revision": "r1", "payload": payload}),
            "send": client.post(f"{BASE}/boards/{slug}/rounds", json={"client_round_id": str(uuid.uuid4()), "revision": "r1", "payload": payload})}


def row_of(env, slug: str) -> Dict[str, Any]:
    return json.loads((env.board(slug) / "sidecar.json").read_text())["revisions"][0]


@pytest.mark.parametrize("layer,payload", [(QUESTIONS, GOOD_Q), (ROWS, GOOD_R)], ids=["questions", "rows"])
def test_a_payload_that_fits_the_layer_is_taken_at_every_door(world, layer, payload) -> None:
    env, client = world
    slug = make_board(world, layer)
    for door, response in doors(client, slug, payload).items():
        assert response.status_code == 200, (door, response.text)
    row = row_of(env, slug)
    assert row["draft"]["payload"] == payload and row["saves"][-1]["payload"] == payload


def edited(base: Dict[str, Any], edit: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    edit(out)
    return out


BAD_Q = [
    ("wrong layer name", lambda p: p.update(layer="rows"), "not a questions layer v1"),
    ("wrong version", lambda p: p.update(v=2), "not a questions layer v1"),
    ("no layer name", lambda p: p.pop("layer"), "not a questions layer v1"),
    ("extra envelope key", lambda p: p.update(picks={}), "picks"),
    ("values not an object", lambda p: p.update(values=[]), "values is an object"),
    ("unknown item", lambda p: p["values"].update(ghost=1), "values.ghost: the layer has no item ghost"),
    ("yesno gets a string", lambda p: p["values"].update({"keep-rail": "yes"}), "values.keep-rail"),
    ("toggle gets a number", lambda p: p["values"].update(dense=1), "values.dense"),
    ("choice outside its options", lambda p: p["values"].update(density="z"), "values.density"),
    ("multi over max", lambda p: p["values"].update(panels=["a", "b", "c"]), "values.panels"),
    ("multi repeats an option", lambda p: p["values"].update(panels=["a", "a"]), "values.panels"),
    ("multi outside its options", lambda p: p["values"].update(panels=["z"]), "values.panels"),
    ("rank missing an option", lambda p: p["values"].update(order=["a", "b"]), "values.order: a rank value lists every option id once"),
    ("rank with a repeat", lambda p: p["values"].update(order=["a", "a", "b"]), "values.order"),
    ("text too long", lambda p: p["values"].update(name="x" * 301), "values.name"),
    ("longtext over 4000", lambda p: p["values"].update(why="x" * 4001), "values.why"),
    ("number below min", lambda p: p["values"].update(size=0), "values.size"),
    ("number above max", lambda p: p["values"].update(size=11), "values.size"),
    ("number is a bool", lambda p: p["values"].update(size=True), "values.size"),
    ("date outside its range", lambda p: p["values"].update(due="2027-01-01"), "values.due"),
    ("date that is no day", lambda p: p["values"].update(due="2026-02-31"), "values.due"),
    ("note for an unknown item", lambda p: p["notes"].update(ghost="x"), "notes.ghost"),
    ("note over 4000", lambda p: p["notes"].update({"keep-rail": "x" * 4001}), "notes.keep-rail"),
    ("a canvas-shaped payload", lambda p: (p.clear(), p.update(picks={"a": 1})), "picks"),
]


@pytest.mark.parametrize("name,edit,message", BAD_Q, ids=[b[0] for b in BAD_Q])
def test_a_questions_payload_that_does_not_fit_is_refused_naming_the_item(world, name: str, edit, message: str) -> None:
    env, client = world
    slug = make_board(world, QUESTIONS)
    before = (env.board(slug) / "sidecar.json").read_bytes()
    for door, response in doors(client, slug, edited(GOOD_Q, edit)).items():
        assert response.status_code == 422, (name, door, response.text)
        assert message in response.json()["detail"]["detail"], (name, door, response.text)
    assert (env.board(slug) / "sidecar.json").read_bytes() == before


BAD_R = [
    ("pick outside the row's own choices", lambda p: p["values"].update({"aw-002": "ok"}), "values.aw-002"),
    ("layer pick on a row with its own choices", lambda p: p["values"].update({"aw-002": "later"}), "values.aw-002"),
    ("own pick on a layer-choices row", lambda p: p["values"].update({"aw-001": "keep"}), "values.aw-001"),
    ("a list on a pick-one layer", lambda p: p["values"].update({"aw-001": ["ok"]}), "values.aw-001"),
    ("unknown row", lambda p: p["values"].update(ghost="ok"), "values.ghost"),
    ("note for an unknown row", lambda p: p["notes"].update(ghost="x"), "notes.ghost"),
    ("a questions envelope", lambda p: p.update(layer="questions"), "not a rows layer v1"),
]


@pytest.mark.parametrize("name,edit,message", BAD_R, ids=[b[0] for b in BAD_R])
def test_a_rows_payload_that_does_not_fit_is_refused_naming_the_row(world, name: str, edit, message: str) -> None:
    env, client = world
    slug = make_board(world, ROWS)
    for door, response in doors(client, slug, edited(GOOD_R, edit)).items():
        assert response.status_code == 422, (name, door, response.text)
        assert message in response.json()["detail"]["detail"], (name, door, response.text)
    assert "draft" not in row_of(env, slug) and "saves" not in row_of(env, slug)


def test_a_pick_several_layer_takes_lists_of_the_rows_choices(world) -> None:
    env, client = world
    several = {**ROWS, "pick": "several", "rows": [{"id": "aw-001", "title": "first"}, {"id": "aw-002", "title": "second", "default": ["ok"]}]}
    slug = make_board(world, several)
    good = {"layer": "rows", "v": 1, "values": {"aw-001": ["ok", "later"], "aw-002": []}}
    assert doors(client, slug, good)["draft"].status_code == 200
    for bad in (["ok", "ok"], ["nope"], "ok"):
        assert doors(client, slug, {**good, "values": {"aw-001": bad}})["draft"].status_code == 422


@pytest.mark.parametrize("canvas", ["payload_mode", "alias"])
def test_a_canvas_payload_is_taken_as_it_is(world, canvas: str) -> None:
    env, client = world
    if canvas == "payload_mode":
        slug = make_board(world, None)
    else:
        item = huddle_store(env).add("all", "canvas", actor="claude", title="Canvas")["id"]
        slug = client.post(f"{BASE}/boards", json=create_body(item, prompts=[], anchors=[], layer={"kind": "canvas"})).json()["slug"]
    free = {"picks": {"aw-1": "ok"}, "layer": "whatever", "v": 9, "notes": [1, 2]}
    for door, response in doors(client, slug, free).items():
        assert response.status_code == 200, (door, response.text)


def test_the_checker_is_pure_and_names_every_misfit_at_once() -> None:
    layer = layer_payload.LAYER_ADAPTER.validate_python(QUESTIONS)
    found = layer_payload.problems(layer, {"layer": "questions", "v": 1, "values": {"keep-rail": 3, "dense": 3, "ghost": 1}, "notes": 5})
    assert len(found) == 4 and any("notes is an object" in f for f in found)
    assert layer_payload.problems(layer, GOOD_Q) == []
