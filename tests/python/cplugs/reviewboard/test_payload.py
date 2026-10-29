
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from src.cplugs.reviewboard import document, payloads, round_text
from src.cplugs.reviewboard.requests import SaveBody
from src.cplugs.reviewboard.schema import MAX_PAYLOAD_BYTES, MAX_SAVES
from tests.python.cplugs.reviewboard.boards import SIDECAR, sidecar as base_sidecar
from tests.python.cplugs.reviewboard.harness import BASE, Env, task_manager_on, task_manager_store, make_env
from tests.python.cplugs.reviewboard.test_publish import create_body


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path)
    ctx = task_manager_on(env, monkeypatch)
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as client:
        yield env, client, ctx
    board_port.unregister()


@pytest.fixture
def board(world):
    env, client, _ctx = world
    item = task_manager_store(env).add("all", "pick the menu", actor="claude", title="Menu picker")["id"]
    r = client.post(f"{BASE}/boards", json=create_body(item, prompts=[], anchors=[], payload_mode=True))
    assert r.status_code == 200, r.text
    return r.json()["slug"], item


def sidecar_of(env: Env, slug: str) -> dict:
    return json.loads((env.board(slug) / "sidecar.json").read_text())


def save(client, slug: str, payload, **over):
    return client.post(f"{BASE}/boards/{slug}/saves", json={"revision": "r1", "payload": payload, **over})


def send(client, slug: str, payload, **over):
    return client.post(f"{BASE}/boards/{slug}/rounds", json={"client_round_id": str(uuid.uuid4()), "revision": "r1", "payload": payload, **over})


def test_an_old_sidecar_loads_and_round_trips_with_no_payload_keys() -> None:
    text = document.canonical_text(document.parse_sidecar(SIDECAR))
    assert "payload" not in text and "saves" not in text
    assert json.loads(text) == SIDECAR


def test_payload_mode_and_saves_round_trip_byte_for_byte() -> None:
    raw = base_sidecar()
    raw["revisions"][0]["payload_mode"] = True
    raw["revisions"][0]["saves"] = [{"n": 1, "at": "2026-10-13T15:00:00Z", "payload": {}}, {"n": 2, "at": "2026-10-13T15:01:00Z", "payload": {"a": [1, {"b": None}]}, "note": "x"}]
    raw["rounds"] = [{**raw["rounds"][0], "answers": [], "anchor_notes": [], "unanswered": [], "payload": {"a": [1, {"b": None}]}, "save": 2,
                      "diff": {"added": ["a"], "removed": [], "changed": [], "more": 0}}]
    text = document.canonical_text(document.parse_sidecar(raw))
    assert json.loads(text) == raw
    assert document.canonical_text(document.parse_sidecar(json.loads(text))) == text
    empty_send = copy.deepcopy(raw)
    empty_send["rounds"][0].update(payload={}, save=1)
    assert json.loads(document.canonical_text(document.parse_sidecar(empty_send)))["rounds"][0]["payload"] == {}


def test_the_rules_hold_saves_to_payload_revisions_and_a_gapless_run() -> None:
    raw = base_sidecar()
    raw["revisions"][0]["saves"] = [{"n": 1, "at": "2026-10-13T15:00:00Z", "payload": {}}]
    with pytest.raises(document.SidecarInvalid, match="only a revision with payload_mode"):
        document.parse_sidecar(raw)
    raw["revisions"][0].update(payload_mode=True, saves=[{"n": 2, "at": "2026-10-13T15:00:00Z", "payload": {}}])
    with pytest.raises(document.SidecarInvalid, match="no gap"):
        document.parse_sidecar(raw)
    raw["revisions"][0]["saves"] = [{"n": 1, "at": "2026-10-13T15:00:00Z", "payload": {"a": 1}}]
    raw["rounds"][0].update(answers=[], anchor_notes=[], unanswered=[], payload={"a": 2}, save=1)
    with pytest.raises(document.SidecarInvalid, match="differs from r1's save 1"):
        document.parse_sidecar(raw)


def test_a_revision_declares_payload_mode_and_it_reaches_the_sidecar(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    assert sidecar_of(env, slug)["revisions"][0]["payload_mode"] is True
    plain = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2 plain", "html": "<p>2</p>"})
    assert plain.status_code == 200
    assert "payload_mode" not in sidecar_of(env, slug)["revisions"][1]


def test_saves_are_numbered_and_every_one_is_kept(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    page = (env.board(slug) / "r001.html").read_bytes()
    first = save(client, slug, {"milk": False}).json()
    second = save(client, slug, {"milk": True}, note="milk yes").json()
    assert first["save"]["n"] == 1 and second["save"]["n"] == 2 and second["save"]["note"] == "milk yes" and "note" not in first["save"]
    saves = sidecar_of(env, slug)["revisions"][0]["saves"]
    assert [(s["n"], s["payload"]) for s in saves] == [(1, {"milk": False}), (2, {"milk": True})]
    assert (env.board(slug) / "r001.html").read_bytes() == page
    assert sidecar_of(env, slug)["rounds"] == []
    assert env.published.count("cplug.reviewboard.boards") >= 3


def test_a_save_is_refused_on_a_normal_revision_and_on_a_missing_one(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2 plain", "html": "<p>2</p>"})
    before = (env.board(slug) / "sidecar.json").read_bytes()
    assert save(client, slug, {"a": 1}, revision="r2").status_code == 422
    assert save(client, slug, {"a": 1}, revision="r9").status_code == 422
    assert (env.board(slug) / "sidecar.json").read_bytes() == before


@pytest.mark.parametrize("payload", [[1, 2], "text", 7, None])
def test_a_payload_that_is_not_a_json_object_is_refused(world, board, payload) -> None:
    env, client, _ = world
    slug, _item = board
    before = (env.board(slug) / "sidecar.json").read_bytes()
    r = client.post(f"{BASE}/boards/{slug}/saves", content=json.dumps({"revision": "r1", "payload": payload}), headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert (env.board(slug) / "sidecar.json").read_bytes() == before


def test_nan_and_infinity_are_not_payload_data() -> None:
    for bad in ({"x": float("nan")}, {"x": float("inf")}, {"x": {1, 2}}, {"x": b"raw"}):
        with pytest.raises(ValidationError, match="plain JSON"):
            SaveBody.model_validate({"revision": "r1", "payload": bad})


def test_a_payload_over_64_kib_is_refused_on_save_and_on_send(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    ok = {"pad": "x" * (MAX_PAYLOAD_BYTES - 40)}
    assert save(client, slug, ok).status_code == 200
    big = {"pad": "x" * MAX_PAYLOAD_BYTES}
    assert save(client, slug, big).status_code == 422
    assert send(client, slug, big).status_code == 422
    assert len(sidecar_of(env, slug)["revisions"][0]["saves"]) == 1 and sidecar_of(env, slug)["rounds"] == []


def test_a_payload_nested_too_deep_is_refused(world, board) -> None:
    _env, client, _ = world
    slug, _item = board
    deep: dict = {}
    node = deep
    for _ in range(40):
        node["n"] = {}
        node = node["n"]
    assert save(client, slug, deep).status_code == 422


def test_a_stale_etag_refuses_a_save_and_writes_nothing(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    seen = client.get(f"{BASE}/boards/{slug}").json()["etag"]
    assert save(client, slug, {"a": 1}).status_code == 200
    before = (env.board(slug) / "sidecar.json").read_bytes()
    stale = save(client, slug, {"a": 2}, base_etag=seen)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "reviewboard_stale"
    assert (env.board(slug) / "sidecar.json").read_bytes() == before
    fresh = client.get(f"{BASE}/boards/{slug}").json()["etag"]
    assert save(client, slug, {"a": 2}, base_etag=fresh).status_code == 200


def test_saves_stop_at_the_cap_with_a_clear_refusal(world, board, monkeypatch) -> None:
    env, client, _ = world
    slug, _item = board
    monkeypatch.setattr(payloads, "MAX_SAVES", 2)
    assert save(client, slug, {"a": 1}).status_code == 200 and save(client, slug, {"a": 2}).status_code == 200
    r = save(client, slug, {"a": 3})
    assert r.status_code == 422 and "saves" in r.json()["detail"]["detail"]
    assert MAX_SAVES == 200


def test_a_send_is_a_save_and_a_round_with_a_diff_in_one_write(world, board) -> None:
    env, client, _ = world
    slug, item = board
    first = send(client, slug, {"milk": True, "eggs": {"n": 2}, "tea": 1}, note="look at my changes and direct me")
    assert first.status_code == 200, first.text
    rnd = first.json()["round"]
    assert rnd["payload"] == {"milk": True, "eggs": {"n": 2}, "tea": 1} and rnd["save"] == 1 and rnd["note"] == "look at my changes and direct me"
    assert rnd["answers"] == [] and rnd["unanswered"] == []
    assert rnd["diff"] == {"added": ["eggs.n", "milk", "tea"], "removed": [], "changed": [], "more": 0}
    second = send(client, slug, {"milk": False, "eggs": {"n": 2}, "bread": [1]}).json()["round"]
    assert second["save"] == 2
    assert second["diff"] == {"previous": "n1", "added": ["bread"], "removed": ["tea"], "changed": ["milk"], "more": 0}
    doc = sidecar_of(env, slug)
    assert [s["n"] for s in doc["revisions"][0]["saves"]] == [1, 2] and doc["revisions"][0]["saves"][0]["note"] == "look at my changes and direct me"
    assert [r["id"] for r in doc["rounds"]] == ["n1", "n2"]
    texts = [m["text"] for m in task_manager_store(env).item(item)["thread"] if m.get("board_round")]
    assert texts[1].startswith(f"review the payload: round n2 on board {slug} (r1, save 2")
    assert "note: look at my changes and direct me" in texts[0] and texts[0].startswith(f"review the payload: round n1 on board {slug}")
    for text in texts:
        assert "milk" not in text and "since n" not in text and "added" not in text and "task_manager_board_get" in text and len(text) < 400


def test_a_send_goes_through_the_same_delivery_as_any_round(world, board) -> None:
    env, client, _ = world
    slug, item = board
    rid = str(uuid.uuid4())
    out = send(client, slug, {"a": 1}, client_round_id=rid).json()
    assert out["delivery"]["state"] == "posted" and out["duplicate"] is False
    message = [m for m in task_manager_store(env).item(item)["thread"] if m.get("board_round")][-1]
    assert message["author"] == "joe" and message["board_round"] == {"slug": slug, "round": "n1", "revision": "r1"}
    again = send(client, slug, {"a": 1, "b": 2}, client_round_id=rid).json()
    assert again["duplicate"] is True and again["round"]["payload"] == {"a": 1}
    doc = sidecar_of(env, slug)
    assert len(doc["rounds"]) == 1 and len(doc["revisions"][0]["saves"]) == 1
    assert len([m for m in task_manager_store(env).item(item)["thread"] if m.get("board_round")]) == 1


def test_a_payload_send_is_refused_where_it_does_not_belong(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2 plain", "html": "<p>2</p>", "prompts": [{"id": "ok", "kind": "check", "label": "fine?"}]})
    before = (env.board(slug) / "sidecar.json").read_bytes()
    assert send(client, slug, {"a": 1}, revision="r2").status_code == 422
    no_payload = client.post(f"{BASE}/boards/{slug}/rounds", json={"client_round_id": str(uuid.uuid4()), "revision": "r1", "note": "hi"})
    assert no_payload.status_code == 422
    mixed = send(client, slug, {"a": 1}, answers=[{"prompt": "ok", "checked": True}])
    assert mixed.status_code == 422
    assert (env.board(slug) / "sidecar.json").read_bytes() == before


def test_a_stale_etag_refuses_a_send_too(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    seen = client.get(f"{BASE}/boards/{slug}").json()["etag"]
    save(client, slug, {"a": 1})
    before = (env.board(slug) / "sidecar.json").read_bytes()
    assert send(client, slug, {"a": 2}, base_etag=seen).status_code == 409
    assert (env.board(slug) / "sidecar.json").read_bytes() == before


def test_the_diff_walks_objects_and_treats_lists_as_values() -> None:
    assert payloads.diff({"a": {"b": 1, "c": 2}, "l": [1]}, {"a": {"b": 1, "c": 3, "d": 4}, "l": [1, 2]}, "n4") == {
        "previous": "n4", "added": ["a.d"], "removed": [], "changed": ["a.c", "l"], "more": 0}
    assert payloads.diff({}, {}, None) == {"added": [], "removed": [], "changed": [], "more": 0}
    many = payloads.diff({}, {f"k{i:03d}": i for i in range(120)}, None)
    assert len(many["added"]) == 50 and many["more"] == 70


def test_the_agent_reads_saves_and_payload_rounds_through_the_get_tool(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    save(client, slug, {"a": 1})
    send(client, slug, {"a": 2}, note="direct me")
    ok, out = env.call("task_manager_board_get", {"board": slug})
    assert ok and [s["n"] for s in out["sidecar"]["revisions"][0]["saves"]] == [1, 2]
    assert out["sidecar"]["rounds"][0]["payload"] == {"a": 2} and out["sidecar"]["rounds"][0]["diff"]["changed"] == []
    ok, latest = env.call("task_manager_board_get", {"board": slug, "saves": "latest"})
    assert [s["n"] for s in latest["sidecar"]["revisions"][0]["saves"]] == [2] and latest["sidecar"]["rounds"][0]["payload"] == {"a": 2}
    ok, none = env.call("task_manager_board_get", {"board": slug, "saves": "none", "since_round": 0})
    assert "saves" not in none["sidecar"]["revisions"][0] and len(none["sidecar"]["rounds"]) == 1
    ok, bad = env.call("task_manager_board_get", {"board": slug, "saves": "some"})
    assert not ok and "saves is one of" in bad


def test_the_agent_publishes_a_payload_revision_through_the_revise_tool(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    ok, out = env.call("task_manager_board_revision_add", {"board": slug, "summary": "r2 picker", "html": "<p>2</p>", "payload_mode": True})
    assert ok, out
    assert sidecar_of(env, slug)["revisions"][1]["payload_mode"] is True


def test_round_text_for_a_payload_round_stays_under_the_task_manager_limit() -> None:
    raw = base_sidecar()
    raw["revisions"][0]["payload_mode"] = True
    raw["revisions"][0]["saves"] = [{"n": 1, "at": "2026-10-13T15:00:00Z", "payload": {"a": 1}}]
    paths = [f"{'p' * 190}{i:03d}" for i in range(50)]
    raw["rounds"] = [{**raw["rounds"][0], "answers": [], "anchor_notes": [], "unanswered": [], "payload": {"a": 1}, "save": 1,
                      "diff": {"added": paths, "removed": paths, "changed": paths, "more": 9}}]
    parsed = document.parse_sidecar(raw)
    text = round_text.summary("t", "20261013-bottom-bar", parsed.revisions[0], parsed.rounds[0])
    assert len(text) <= round_text.LIMIT and text.endswith('"since_round": 0}')
    assert "pppp" not in text




def draft(client, slug: str, payload, **over):
    return client.put(f"{BASE}/boards/{slug}/payload-draft", json={"revision": "r1", "payload": payload, **over})


def test_the_draft_overwrites_in_place_and_is_never_a_numbered_save(world, board) -> None:
    env, client, _ = world
    slug, item = board
    first = draft(client, slug, {"milk": False})
    assert first.status_code == 200 and first.json()["changed"] is True and first.json()["draft"]["at"]
    second = draft(client, slug, {"milk": True})
    assert second.json()["changed"] is True
    row = sidecar_of(env, slug)["revisions"][0]
    assert row["draft"]["payload"] == {"milk": True} and "saves" not in row
    assert sidecar_of(env, slug)["rounds"] == []
    assert [m for m in task_manager_store(env).item(item)["thread"] if m.get("board_round")] == []
    assert save(client, slug, {"milk": True}).json()["save"]["n"] == 1


def test_the_same_draft_again_writes_nothing(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    draft(client, slug, {"a": 1})
    before = (env.board(slug) / "sidecar.json").read_bytes()
    marks = env.published.count("cplug.reviewboard.boards")
    again = draft(client, slug, {"a": 1})
    assert again.status_code == 200 and again.json()["changed"] is False
    assert (env.board(slug) / "sidecar.json").read_bytes() == before and env.published.count("cplug.reviewboard.boards") == marks


@pytest.mark.parametrize("payload", [[1, 2], "text", None])
def test_a_draft_that_is_not_a_json_object_is_refused(world, board, payload) -> None:
    env, client, _ = world
    slug, _item = board
    before = (env.board(slug) / "sidecar.json").read_bytes()
    assert draft(client, slug, payload).status_code == 422
    assert (env.board(slug) / "sidecar.json").read_bytes() == before


def test_a_draft_is_held_to_the_payload_limits(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    assert draft(client, slug, {"blob": "x" * (MAX_PAYLOAD_BYTES + 1)}).status_code == 422
    deep: dict = {}
    node = deep
    for _ in range(40):
        node["n"] = {}
        node = node["n"]
    assert draft(client, slug, deep).status_code == 422
    assert "draft" not in sidecar_of(env, slug)["revisions"][0]


def test_a_draft_is_refused_on_a_normal_revision_and_a_missing_one(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2 plain", "html": "<p>2</p>"})
    assert draft(client, slug, {"a": 1}, revision="r2").status_code == 422
    assert draft(client, slug, {"a": 1}, revision="r9").status_code == 422


def test_the_draft_is_not_a_save_cap_victim(world, board, monkeypatch) -> None:
    env, client, _ = world
    slug, _item = board
    monkeypatch.setattr(payloads, "MAX_SAVES", 1)
    assert save(client, slug, {"a": 1}).status_code == 200 and save(client, slug, {"a": 2}).status_code == 422
    assert draft(client, slug, {"a": 3}).status_code == 200


def test_a_sidecar_with_a_draft_round_trips_and_an_old_one_is_unchanged() -> None:
    assert "draft" not in document.canonical_text(document.parse_sidecar(SIDECAR))
    raw = base_sidecar()
    raw["revisions"][0]["payload_mode"] = True
    raw["revisions"][0]["draft"] = {"at": "2026-10-14T09:00:00Z", "payload": {"items": {"milk": True}}}
    text = document.canonical_text(document.parse_sidecar(raw))
    assert json.loads(text) == raw and document.canonical_text(document.parse_sidecar(json.loads(text))) == text
    raw["revisions"][0]["draft"]["payload"] = {}
    assert json.loads(document.canonical_text(document.parse_sidecar(raw)))["revisions"][0]["draft"]["payload"] == {}
    plain = base_sidecar()
    plain["revisions"][0]["draft"] = {"at": "2026-10-14T09:00:00Z", "payload": {"a": 1}}
    with pytest.raises(document.SidecarInvalid, match="only a revision with payload_mode holds a draft"):
        document.parse_sidecar(plain)


def test_the_get_tool_shows_the_draft_even_when_saves_are_left_out(world, board) -> None:
    env, client, _ = world
    slug, _item = board
    save(client, slug, {"a": 1})
    draft(client, slug, {"a": 2})
    for mode in ("all", "latest", "none"):
        ok, out = env.call("task_manager_board_get", {"board": slug, "saves": mode})
        assert ok, out
        assert '"a": 2' in json.dumps(out), mode
