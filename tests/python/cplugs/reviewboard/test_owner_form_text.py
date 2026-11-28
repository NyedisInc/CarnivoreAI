
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.auth import require_auth
from src.plugins.taskmanager import board_port
from src.main import _validation_error_as_400
from src.plugins.reviewboard.live_requests import LiveBody, LiveSendBody, MilestoneBody
from src.plugins.reviewboard.requests import MAX_RAW_STRING, ReviseBody
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_on, task_manager_store, make_env
from tests.python.cplugs.reviewboard.test_publish import create_body
from tests.python.cplugs.test_owner_text import CLEAN_LOG, COLORED_LOG, REFUSED, STRIPPED

BAD = sorted(REFUSED)


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path)
    task_manager_on(env, monkeypatch)
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    env.app.add_exception_handler(RequestValidationError, _validation_error_as_400)
    with TestClient(env.app) as client:
        store = task_manager_store(env)
        plain = client.post(f"{BASE}/boards", json=create_body(store.add("all", "bar", actor="claude", title="Bar")["id"])).json()["slug"]
        payload = client.post(f"{BASE}/boards", json=create_body(store.add("all", "menu", actor="claude", title="Menu")["id"], slug_name="menu",
                                                                  prompts=[], anchors=[], payload_mode=True)).json()["slug"]
        yield env, client, plain, payload
    board_port.unregister()


def round_body(note: str = "closer", answer_note: str = "", anchor: str = "too close") -> dict:
    return {"client_round_id": str(uuid.uuid4()), "revision": "r1",
            "answers": [{"prompt": "layout", "options": ["b"], "note": answer_note}, {"prompt": "padding", "checked": True}],
            "anchor_notes": [{"anchor": "send", "text": anchor}], "note": note}


def sidecar(env, slug: str) -> dict:
    return json.loads((env.board(slug) / "sidecar.json").read_text())


def refused(response, field: str) -> bool:
    return response.status_code == 400 and f"{field} may not contain hidden or control characters" in response.text


@pytest.mark.parametrize("name", BAD)
def test_a_round_refuses_hidden_text_in_every_field_and_names_it(world, name: str) -> None:
    env, client, slug, _ = world
    bad = f"ok{REFUSED[name]}"
    for body, field in ((round_body(note=bad), "note"), (round_body(answer_note=bad), "answers.0.note"), (round_body(anchor=bad), "anchor_notes.0.text")):
        r = client.post(f"{BASE}/boards/{slug}/rounds", json=body)
        assert refused(r, field), (name, field, r.status_code, r.text)
    assert not sidecar(env, slug).get("rounds")


@pytest.mark.parametrize("name", BAD)
def test_a_draft_refuses_hidden_text(world, name: str) -> None:
    _env, client, slug, _ = world
    d = {"rev": 0, "revision": "r1", "answers": [], "anchor_notes": [], "note": f"half{REFUSED[name]}", "client_round_id": str(uuid.uuid4())}
    assert refused(client.put(f"{BASE}/boards/{slug}/draft", json=d), "note")
    assert client.get(f"{BASE}/boards/{slug}/draft").json() == {"draft": None}


@pytest.mark.parametrize("name", BAD)
def test_payload_saves_and_autosaves_refuse_hidden_text_anywhere_in_the_payload(world, name: str) -> None:
    _env, client, _, slug = world
    hidden = REFUSED[name]
    for payload in ({"items": [{"label": f"milk{hidden}"}]}, {f"k{hidden}": True}):
        assert client.post(f"{BASE}/boards/{slug}/saves", json={"revision": "r1", "payload": payload}).status_code == 400
        assert client.put(f"{BASE}/boards/{slug}/payload-draft", json={"revision": "r1", "payload": payload}).status_code == 400
        send = {"client_round_id": str(uuid.uuid4()), "revision": "r1", "payload": payload}
        assert client.post(f"{BASE}/boards/{slug}/rounds", json=send).status_code == 400
    assert refused(client.post(f"{BASE}/boards/{slug}/saves", json={"revision": "r1", "payload": {}, "note": f"x{hidden}"}), "note")


@pytest.mark.parametrize("name", BAD)
def test_the_live_bodies_refuse_hidden_text(name: str) -> None:
    hidden = REFUSED[name]
    with pytest.raises(ValidationError, match="note may not contain hidden"):
        LiveSendBody.model_validate({"client_round_id": str(uuid.uuid4()), "note": f"ok{hidden}"})
    with pytest.raises(ValidationError, match="summary may not contain hidden"):
        LiveBody.model_validate({"summary": f"draft{hidden}", "html": "<p>x</p>"})
    with pytest.raises(ValidationError, match="name may not contain hidden"):
        MilestoneBody.model_validate({"name": f"v1{hidden}"})


@pytest.mark.parametrize("name", BAD)
def test_agent_written_board_text_refuses_hidden_text(world, name: str) -> None:
    env, client, slug, _ = world
    hidden = REFUSED[name]
    item = task_manager_store(env).add("all", "other", actor="claude", title="Other")["id"]
    assert refused(client.post(f"{BASE}/boards", json=create_body(item, slug_name="t1", title=f"bar{hidden}")), "title")
    assert refused(client.post(f"{BASE}/boards", json=create_body(item, slug_name="t2", summary=f"s{hidden}")), "summary")
    first = create_body(item)["prompts"][0]
    assert refused(client.post(f"{BASE}/boards", json=create_body(item, slug_name="t3", prompts=[{**first, "label": f"p{hidden}"}])), "prompts.0.label")
    assert refused(client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": f"r2{hidden}", "html": "<p>x</p>"}), "summary")


@pytest.mark.parametrize("name", sorted(STRIPPED))
def test_a_pastes_accidents_are_cleaned_and_stored_clean(world, name: str) -> None:
    env, client, slug, payload_slug = world
    junk = STRIPPED[name]
    assert client.post(f"{BASE}/boards/{slug}/rounds", json=round_body(note=f"clo{junk}ser")).status_code == 200
    assert sidecar(env, slug)["rounds"][-1]["note"] == "closer"
    saved = client.post(f"{BASE}/boards/{payload_slug}/saves", json={"revision": "r1", "payload": {f"a{junk}": f"b{junk}"}})
    assert saved.status_code == 200 and saved.json()["save"]["payload"] == {"a": "b"}, saved.text


def test_a_colored_log_and_long_lines_come_through_clean_and_the_page_is_untouched(world) -> None:
    env, client, slug, _ = world
    note = COLORED_LOG + "\n" + "\n".join(f"\tframe {n}" for n in range(80)) + "\n\n\n\nend"
    r = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body(note=note))
    assert r.status_code == 200, r.text
    assert sidecar(env, slug)["rounds"][-1]["note"] == CLEAN_LOG + "\n" + "\n".join(f"\tframe {n}" for n in range(80)) + "\n\n\n\nend"
    page = "<p>\u00a0nbsp\u200b stays</p>"
    r = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2\u200b", "html": page})
    assert r.status_code == 200, r.text
    assert sidecar(env, slug)["revisions"][-1]["summary"] == "r2"
    assert any(page in p.read_text() for p in env.board(slug).rglob("*.html")), "the page HTML is stored exactly as sent"


@pytest.mark.parametrize("route", ["payload-draft", "rounds", "saves", "live/send"])
def test_a_2000_deep_body_is_refused_never_a_500(world, route: str) -> None:
    _env, client, _, slug = world
    deep: dict = {}
    node = deep
    for _ in range(2000):
        node["a"] = {}
        node = node["a"]
    body = {"revision": "draft" if route == "live/send" else "r1", "payload": deep, "client_round_id": str(uuid.uuid4())}
    if route in ("payload-draft", "saves"):
        body.pop("client_round_id")
    if route == "live/send":
        body = {"client_round_id": body["client_round_id"], "note": "x", "answers": [{"prompt": "p", "note": deep}]}
    call = client.put if route == "payload-draft" else client.post
    r = call(f"{BASE}/boards/{slug}/{route}", json=body)
    assert r.status_code == 400 and "nests deeper" in r.text, (route, r.status_code, r.text[:300])


def test_only_a_page_string_at_a_page_path_is_kept_as_sent() -> None:
    for bad in ({"html": {"note": "\u202e"}}, {"html": "<p>x</p>", "views": [{"id": "v", "label": "v", "html": "<p>y</p>", "x": {"html": "\u202e"}}]}):
        with pytest.raises(ValidationError):
            ReviseBody.model_validate({"summary": "r2", **bad})
    with pytest.raises(ValidationError, match="payload.html may not contain hidden"):
        LiveSendBody.model_validate({"client_round_id": str(uuid.uuid4()), "payload": {"html": "\u202e"}})
    body = ReviseBody.model_validate({"summary": "r2", "html": "<p>\u202e</p>", "views": [{"id": "v", "label": "v", "html": "<b>\u200b</b>"}]})
    assert body.html == "<p>\u202e</p>" and body.views[0].html == "<b>\u200b</b>"


def test_a_string_past_the_raw_cap_is_refused_unread() -> None:
    with pytest.raises(ValidationError, match=f"note is over {MAX_RAW_STRING} characters"):
        LiveSendBody.model_validate({"client_round_id": str(uuid.uuid4()), "note": "\x9d" * (MAX_RAW_STRING + 1)})
