
from __future__ import annotations

from tests.python.cplugs.huddle.test_task_manager_focus import add, client, setup  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_groups import BASE, body, group


def folds(client, key: str = "all") -> dict:
    return {g["id"]: g["folded"] for g in body(client, key)["groups"]}


def test_many_groups_fold_and_unfold_in_one_write(client, setup):
    add(client, "all", "row")
    a, b, c = group(client, "all", "a"), group(client, "all", "b"), group(client, "all", "c")
    shut = client.post(f"{BASE}/groups/fold", json={"ids": [a, b], "folded": True})
    assert shut.status_code == 200, shut.text
    assert shut.json() == {"folded": True, "updated": [a, b], "missing": []}
    assert folds(client) == {a: True, b: True, c: False}
    opened = client.post(f"{BASE}/groups/fold", json={"ids": [a, b, c], "folded": False})
    assert opened.json()["updated"] == [a, b, c]
    assert folds(client) == {a: False, b: False, c: False}


def test_a_removed_group_is_reported_and_the_rest_still_fold(client, setup):
    a, gone = group(client, "all", "a"), group(client, "all", "gone")
    client.delete(f"{BASE}/groups/{gone}")
    answer = client.post(f"{BASE}/groups/fold", json={"ids": [gone, a, 9999], "folded": True}).json()
    assert answer == {"folded": True, "updated": [a], "missing": [gone, 9999]}
    assert folds(client) == {a: True}


def test_a_body_that_is_not_ids_and_a_bool_is_refused(client, setup):
    a = group(client, "all", "a")
    for bad in ({"ids": [a], "folded": "yes"}, {"ids": ["1"], "folded": True}, {"ids": [a]}, {"ids": [a], "folded": True, "x": 1}):
        assert client.post(f"{BASE}/groups/fold", json=bad).status_code == 422, bad
    assert folds(client) == {a: False}
