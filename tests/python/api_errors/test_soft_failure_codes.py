
from __future__ import annotations

import sqlite3

from src.api import hosts_routes

from .conftest import LEAK


def test_hosts_list_unavailable_answers_a_sentence_not_the_exception(driver, monkeypatch):
    def broken(*_a, **_k):
        raise sqlite3.OperationalError(f"disk I/O error {LEAK}")

    monkeypatch.setattr(hosts_routes, "_run", broken)
    response, events = driver.call("GET", "/hosts", None)
    assert response.status_code == 200 and LEAK not in response.text
    body = response.json()
    assert body["status"] == hosts_routes.STATUS_UNAVAILABLE and body["detail"]
    assert any(LEAK in str(e.get("error")) for e in events if e.get("code") == "datastore_unavailable")


def test_a_reported_http_exception_is_its_sentence_not_the_stringified_dict():
    from src.api.error_response import sentence_of

    assert sentence_of({"code": "x", "detail": "no thanks"}) == "no thanks"
    assert sentence_of({"code": "only_code"}) == "only_code"
    assert sentence_of("plain") == "plain"
