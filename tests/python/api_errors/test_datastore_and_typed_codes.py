
from __future__ import annotations

import sqlite3

from src.api import mcp_usage_routes, theme_export_routes

from .conftest import LEAK, assert_fixed


def test_mcp_usage_unreadable_answers_a_code_not_the_exception_type(driver, monkeypatch):
    def broken(_days):
        raise sqlite3.OperationalError(f"disk I/O error {LEAK}")

    monkeypatch.setattr(mcp_usage_routes, "_answer", broken)
    response, events = driver.call("GET", "/mcp-usage", None)
    detail = assert_fixed(response, 503, "datastore_unavailable", events)
    assert "OperationalError" not in response.text and detail["detail"]


def test_theme_export_refusal_answers_its_own_code(driver, monkeypatch):
    refused = theme_export_routes.ThemeExportRefused

    def refuse(*_a, **_k):
        raise refused(404, "theme_unknown", f"no theme at {LEAK}")

    monkeypatch.setattr(theme_export_routes, "read_theme_document", refuse)
    response, events = driver.call("GET", "/themes/nope/export", None)
    assert_fixed(response, 404, "theme_unknown", events)


def test_a_too_short_search_answers_its_code_not_the_sentence(driver):
    response, events = driver.call("GET", "/sessions/scrollback-search?q=a", object())
    assert_fixed(response, 422, "too_short", events, text="type at least")
