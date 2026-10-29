
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.deepsearch import constants as K
from src.core.deepsearch import suggest as suggest_index
from src.core.deepsearch import service
from tests.python.deepsearch.helpers import build_world, cq, drain, go_ready, mount, rec, scan, teardown

URL = "/api/v1/deepsearch/suggest"
MANY = " ".join(f"capword{i:02d}" for i in range(30))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    with open(built["main"], "ab") as handle:
        handle.write(rec(5, MANY) + rec(6, "capmost here") + rec(7, "capmost there") + rec(8, "capmost again"))
    app = mount(built, monkeypatch)
    scan(built)
    drain(built)
    go_ready(built)
    built["app"] = app
    yield built
    teardown()


def test_a_prefix_returns_matching_terms_most_common_first(world):
    with TestClient(world["app"]) as client:
        body = client.get(URL, params={"q": "CAP"}).json()
    assert body["prefix"] == "cap" and body["count"] == len(body["terms"])
    assert body["terms"][0] == {"term": "capmost", "docs": 3}
    assert all(t["term"].startswith("cap") for t in body["terms"])
    with TestClient(world["app"]) as client:
        assert [t["term"] for t in client.get(URL, params={"q": "wombat"}).json()["terms"]] == ["wombatmain"]
        assert client.get(URL, params={"q": "nosuchterm"}).json()["terms"] == []


def test_the_prefix_must_be_long_enough_and_not_a_sentence(world):
    with TestClient(world["app"]) as client:
        for q in ("c", " c ", "", "x" * (suggest_index.SUGGEST_MAX_CHARS + 1)):
            refused = client.get(URL, params={"q": q})
            assert refused.status_code == 422 and refused.json()["detail"]["code"] == "deepsearch_invalid", q


def test_the_services_limits_equal_the_index_modules():
    assert (service.SUGGEST_LIMIT_DEFAULT, service.SUGGEST_LIMIT_MAX) == (
        suggest_index.SUGGEST_LIMIT_DEFAULT, suggest_index.SUGGEST_LIMIT_MAX)


def test_the_answer_is_capped_by_the_default_and_by_the_limit(world):
    with TestClient(world["app"]) as client:
        assert client.get(URL, params={"q": "cap"}).json()["count"] == suggest_index.SUGGEST_LIMIT_DEFAULT
        assert client.get(URL, params={"q": "cap", "limit": 3}).json()["count"] == 3
        assert client.get(URL, params={"q": "cap", "limit": suggest_index.SUGGEST_LIMIT_MAX}).json()["count"] == 20
        assert client.get(URL, params={"q": "cap", "limit": suggest_index.SUGGEST_LIMIT_MAX + 1}).status_code == 422
        assert client.get(URL, params={"q": "cap", "limit": 0}).status_code == 422


def test_the_route_needs_auth(world):
    def refuse() -> None:
        raise HTTPException(status_code=401, detail="unauthenticated")

    world["app"].dependency_overrides[require_auth] = refuse
    with TestClient(world["app"]) as client:
        assert client.get(URL, params={"q": "cap"}).status_code == 401
    world["app"].dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(world["app"]) as client:
        assert client.get(URL, params={"q": "cap"}).status_code == 200


@pytest.mark.parametrize("payload", ["' OR 1=1 --", "cap'; DROP TABLE session_search_rows; --", "cap%", "cap_", 'cap"*',
                                     "cap\x00x", "\U0010ffff\U0010ffff"])
def test_a_prefix_is_never_read_as_sql_or_a_pattern(world, payload):
    with TestClient(world["app"]) as client:
        answer = client.get(URL, params={"q": payload})
    assert answer.status_code in (200, 422)
    if answer.status_code == 200:
        assert all(t["term"].startswith(answer.json()["prefix"]) for t in answer.json()["terms"])
    assert cq(world, f"SELECT COUNT(*) FROM {K.ROWS_TABLE}")[0][0] > 0
    with TestClient(world["app"]) as client:
        assert client.get(URL, params={"q": "capmost"}).json()["terms"][0]["term"] == "capmost"
