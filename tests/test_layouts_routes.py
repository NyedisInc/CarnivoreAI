
from __future__ import annotations

from contextlib import closing

import pytest

from tests.layouts_helpers import add_sessions, client_for, grid, row

# ruff: noqa: E402
from src.core.layouts import store as store
from src.core.db import connect
from src.core.layouts.lease import LEASES
from tests.lifecycle_helpers import add_row

API = "/api/v1/layouts"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    client, db_path, frames = client_for(tmp_path, monkeypatch)
    return client, db_path, frames, add_sessions(db_path, 4)


def _create(client, name, *rows_, **extra):
    return client.post(API, json={"name": name, "shape": grid(*[row(r) for r in rows_]), **extra})


def test_create_derives_members_with_both_keys_and_publishes(env):
    client, _, frames, sessions = env
    (a, ua), (b, ub) = sessions[:2]
    res = _create(client, "  api + web ", a, b)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] is True and body["deleted"] is False
    layout = body["layout"]
    assert layout["name"] == "api + web" and layout["revision"] == 1
    assert [(m["session_row_id"], m["session_uuid"]) for m in layout["members"]] == [(a, ua), (b, ub)]
    assert frames[-1] == {"type": frames[-1]["type"], "reason": "layouts"}
    listed = client.get(API).json()
    assert listed["status"] == "ok" and [l["layout_uuid"] for l in listed["layouts"]] == [layout["layout_uuid"]]


def test_names_fold_case_and_are_bounded(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    assert _create(client, "Pair", a, b).status_code == 200
    taken = _create(client, "pAIR", a, b)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "layout_name_taken"
    for bad in ("   ", "x" * 61, "tab\there"):
        res = _create(client, bad, a, b)
        assert res.status_code == 400 and res.json()["detail"]["code"] == "layout_name_invalid", bad
    assert _create(client, "y" * 60, a, b).status_code == 200


def test_the_hundred_and_first_layout_is_refused(env, monkeypatch):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    monkeypatch.setattr(store, "LAYOUT_MAX", 3)
    for i in range(3):
        assert _create(client, f"l{i}", a, b).status_code == 200
    res = _create(client, "l3", a, b)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "layout_limit"
    assert store.LAYOUT_MAX == 3 and len(client.get(API).json()["layouts"]) == 3


def test_source_key_makes_create_idempotent(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    first = _create(client, "migrated", a, b, source_key="terminal_layouts:cloude_x@1").json()
    again = _create(client, "migrated", a, b, source_key="terminal_layouts:cloude_x@1")
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["layout"]["layout_uuid"] == first["layout"]["layout_uuid"]
    assert len(client.get(API).json()["layouts"]) == 1


def test_unresolved_members_and_too_few_are_refused(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    res = _create(client, "ghost", a, 999)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "member_unresolved"
    assert res.json()["detail"]["unresolved"] == [row(999)]
    res = client.post(API, json={"name": "app", "shape": grid(row(a), "terminal:ses_x")})
    assert res.json()["detail"]["unresolved"] == ["terminal:ses_x"]
    res = _create(client, "solo", a)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "layout_too_few_members"
    res = client.post(API, json={"name": "p", "shape": grid("terminal:@primary", row(b))})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "layout_shape_invalid"
    assert client.get(API).json()["layouts"] == []


def test_shape_write_rederives_members_and_a_stale_revision_carries_current(env):
    client, _, _, sessions = env
    (a, _), (b, _), (c, _) = sessions[:3]
    layout = _create(client, "pair", a, b).json()["layout"]
    url = f"{API}/{layout['layout_uuid']}/shape"
    ok = client.put(url, json={"shape": grid(row(a), row(c)), "expected_revision": 1})
    assert ok.status_code == 200
    assert [m["session_row_id"] for m in ok.json()["layout"]["members"]] == [a, c]
    assert ok.json()["layout"]["revision"] == 2
    stale = client.put(url, json={"shape": grid(row(a), row(b)), "expected_revision": 1})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "layout_stale" and detail["current"]["revision"] == 2
    assert [m["session_row_id"] for m in detail["current"]["members"]] == [a, c]


def test_a_shape_of_one_deletes_the_layout_and_names_the_survivor(env):
    client, _, _, sessions = env
    (a, ua), (b, _) = sessions[:2]
    layout = _create(client, "pair", a, b).json()["layout"]
    res = client.put(f"{API}/{layout['layout_uuid']}/shape",
                     json={"shape": grid(row(a)), "expected_revision": 1})
    assert res.status_code == 200
    assert res.json() == {"layout": None, "deleted": True, "created": False,
                          "survivor": {"session_row_id": a, "session_uuid": ua, "position": 0,
                                       "broadcast": True}}
    assert client.get(API).json()["layouts"] == []


def test_members_add_and_remove_down_to_one(env):
    client, _, _, sessions = env
    (a, ua), (b, ub), (c, uc) = sessions[:3]
    layout = _create(client, "pair", a, b).json()["layout"]
    url = f"{API}/{layout['layout_uuid']}/members"
    added = client.post(url, json={"session_uuid": uc}).json()["layout"]
    assert [m["session_uuid"] for m in added["members"]] == [ua, uc, ub]
    again = client.post(url, json={"session_row_id": c}).json()["layout"]
    assert again["revision"] == added["revision"]
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"session_uuid": "nope"}).json()["detail"]["code"] == "member_unresolved"
    assert client.delete(f"{url}/{uc}").json()["layout"]["revision"] == added["revision"] + 1
    last = client.delete(f"{url}/{ub}").json()
    assert last["deleted"] is True and last["survivor"]["session_uuid"] == ua
    assert client.delete(f"{url}/{ua}").status_code == 404


def test_rename_order_and_delete_never_touch_sessions(env):
    client, db_path, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    one = _create(client, "one", a, b).json()["layout"]["layout_uuid"]
    two = _create(client, "two", a, b).json()["layout"]["layout_uuid"]
    renamed = client.patch(f"{API}/{one}", json={"name": "ONE"}).json()["layout"]
    assert renamed["name"] == "ONE" and renamed["revision"] == 1
    assert client.patch(f"{API}/{one}", json={"name": "two"}).status_code == 409
    order = client.put(f"{API}/order", json={"layout_uuids": [two]}).json()
    assert [l["layout_uuid"] for l in order["layouts"]] == [two, one]
    assert client.put(f"{API}/order", json={"layout_uuids": ["nope"]}).status_code == 404
    assert client.delete(f"{API}/{one}").json() == {
        "layout": None, "deleted": True, "survivor": None, "created": False}
    assert client.delete(f"{API}/{one}").status_code == 404
    with closing(connect(db_path, create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 4


def test_a_recycled_tmux_name_does_not_inherit_membership(env):
    client, db_path, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    layout = _create(client, "pair", a, b).json()["layout"]
    with closing(connect(db_path, create=False)) as conn:
        name = conn.execute("SELECT tmux_name FROM sessions WHERE id = ?", (b,)).fetchone()[0]
        reborn = add_row(conn, uuid="reborn-0000", name=name, epoch=9999)
    listed = client.get(API).json()["layouts"][0]
    assert [m["session_row_id"] for m in listed["members"]] == [a, b]
    assert reborn not in [m["session_row_id"] for m in listed["members"]]
    assert listed["revision"] == layout["revision"]


def test_the_active_lease_needs_a_real_layout(env):
    client, _, frames, sessions = env
    (a, _), (b, _) = sessions[:2]
    uuid = _create(client, "pair", a, b).json()["layout"]["layout_uuid"]
    before = len(frames)
    assert client.put(f"{API}/nope/active").status_code == 404
    res = client.put(f"{API}/{uuid}/active")
    assert res.status_code == 200 and res.json() == {
        "layout_uuid": uuid, "active": True, "lease_seconds": 180}
    assert uuid in LEASES.active() and len(frames) == before
    client.delete(f"{API}/{uuid}")
    assert uuid not in LEASES.active()


def test_missing_tables_read_unavailable_and_writes_503(env):
    client, db_path, frames, sessions = env
    (a, _), (b, _) = sessions[:2]
    with closing(connect(db_path, create=False)) as conn:
        conn.execute("DROP TRIGGER tr_sessions_delete_layout_members")
        conn.execute("DROP TABLE layout_members")
        conn.execute("DROP TABLE layouts")
    listed = client.get(API).json()
    assert listed["status"] == "unavailable" and listed["layouts"] == []
    before = len(frames)
    res = _create(client, "pair", a, b)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "layouts_unavailable"
    assert client.put(f"{API}/x/active").status_code == 503
    assert len(frames) == before


def test_a_missing_datastore_reads_unavailable(tmp_path, monkeypatch):
    client, db_path, _ = client_for(tmp_path, monkeypatch)
    db_path.unlink()
    assert client.get(API).json()["status"] == "unavailable"


def _tree(*cells, sizes=None):
    leaves = [{"t": "leaf", "id": c} for c in cells]
    root = leaves[0] if len(leaves) == 1 else {
        "t": "split", "id": "s1", "dir": "h", "unit": "fr",
        "sizes": sizes or [1 / len(leaves)] * len(leaves), "children": leaves}
    layout = {"v": 7, "variants": {"wide": {"root": root}}, "hidden": [], "collapsed": [],
              "heroCollapsed": False}
    return {"layout": layout, "groups": {}}


def test_a_v7_shape_is_stored_and_its_members_follow_the_walk(env):
    client, _, _, sessions = env
    (a, _), (b, _), (c, uc) = sessions[:3]
    shape = _tree(row(b), row(a))
    res = client.post(API, json={"name": "tree", "shape": shape})
    assert res.status_code == 200, res.text
    layout = res.json()["layout"]
    assert [m["session_row_id"] for m in layout["members"]] == [b, a]
    assert layout["shape"] == shape
    url = f"{API}/{layout['layout_uuid']}"
    put = client.put(f"{url}/shape", json={"shape": _tree(row(a), row(b), row(c)), "expected_revision": 1})
    assert put.status_code == 200, put.text
    assert [m["session_row_id"] for m in put.json()["layout"]["members"]] == [a, b, c]
    gone = client.delete(f"{url}/members/{uc}").json()["layout"]
    root = gone["shape"]["layout"]["variants"]["wide"]["root"]
    assert [leaf["id"] for leaf in root["children"]] == [row(a), row(b)]
    assert root["sizes"] == [0.5, 0.5]


def test_a_malformed_v7_shape_is_refused_as_invalid(env):
    client, _, _, sessions = env
    (a, _), (b, _) = sessions[:2]
    bad = _tree(row(a), row(b), sizes=[0.5, 0.6])
    res = client.post(API, json={"name": "bad", "shape": bad})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "layout_shape_invalid"
