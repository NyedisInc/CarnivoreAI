
from __future__ import annotations

from pathlib import Path

import pytest

from src.core import static_asset_keys as keys

SHELL = '<script src="/static/dist/app.js"></script><link rel="stylesheet" href="/static/dist/app.css">'


@pytest.fixture()
def client(tmp_path: Path) -> Path:
    keys.reset_for_tests()
    (tmp_path / "dist").mkdir()
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "dist" / "app.js").write_text("one", encoding="utf-8")
    (tmp_path / "dist" / "app.css").write_text("css", encoding="utf-8")
    return tmp_path


def test_key_is_stable_when_nothing_changes(client: Path) -> None:
    first = keys.client_build_key(client)
    assert first and len(first) == keys.KEY_LENGTH
    assert keys.client_build_key(client) == first


def test_key_moves_when_app_js_content_changes(client: Path) -> None:
    before = keys.client_build_key(client)
    (client / "dist" / "app.js").write_text("two", encoding="utf-8")
    assert keys.client_build_key(client) != before


def test_key_moves_when_the_shell_changes(client: Path) -> None:
    before = keys.client_build_key(client)
    (client / "index.html").write_text(SHELL + "<!-- x -->", encoding="utf-8")
    assert keys.client_build_key(client) != before


def test_key_moves_when_a_referenced_file_disappears(client: Path) -> None:
    before = keys.client_build_key(client)
    (client / "dist" / "app.css").rename(client / "gone.css")
    assert keys.client_build_key(client) != before


def test_key_moves_when_the_popout_bundle_changes(client: Path) -> None:
    (client / "popout.html").write_text('<script src="/static/dist/popout.js"></script>', encoding="utf-8")
    (client / "dist" / "popout.js").write_text("one", encoding="utf-8")
    before = keys.client_build_key(client)
    (client / "dist" / "popout.js").write_text("two", encoding="utf-8")
    assert keys.client_build_key(client) != before


def test_key_is_empty_when_the_shell_is_unreadable(tmp_path: Path) -> None:
    keys.reset_for_tests()
    assert keys.client_build_key(tmp_path) == ""


def test_version_route_reports_client_build(client: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from src.api import version_routes

    monkeypatch.setattr(version_routes, "client_build_key", lambda: keys.client_build_key(client))
    monkeypatch.setattr(version_routes, "_datastore_block", lambda: {})
    body = asyncio.run(version_routes.get_version())
    assert body["client_build"] == keys.client_build_key(client)
