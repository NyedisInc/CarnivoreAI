
from __future__ import annotations

import pytest

from src.cplugs.sdk import restore_points
from src.core.bookmarks import locate, service
from src.core.bookmarks.errors import TranscriptUnavailable
from tests.python.bookmarks import fixtures
from tests.python.bookmarks.test_store_routes_mcp import env  # noqa: F401


def test_add_and_list_work_with_no_plugin_state_at_all(env, monkeypatch):  # noqa: F811
    def boom(*args, **kwargs):
        raise AssertionError("bookmarks must not consult plugin state")

    monkeypatch.setattr("src.cplugs.host.gate.is_on", boom)
    mark = service.add_bookmark("row-uuid-1", label="x")
    assert [b["id"] for b in service.list_bookmarks("row-uuid-1")["bookmarks"]] == [mark.id]


def test_resolution_falls_back_to_the_jsonl_in_another_profile_root(tmp_path):
    default_root, profile_root = tmp_path / "default", tmp_path / "profile"
    default_root.mkdir()
    written = fixtures.write_transcript(profile_root)
    found = locate.resolve_transcript(fixtures.SOURCE, "/some/other/cwd", roots=(default_root, profile_root))
    assert found == written


def test_restore_point_repair_runs_only_when_the_gate_is_on(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(restore_points, "get", lambda: None)
    monkeypatch.setattr(locate, "restore_from_points", lambda conv: calls.append(conv))
    with pytest.raises(TranscriptUnavailable):
        locate.resolve_transcript(fixtures.SOURCE, None, roots=(tmp_path,))
    assert calls == [fixtures.SOURCE]


def test_restore_from_points_refuses_when_the_gate_is_off(monkeypatch):
    monkeypatch.setattr(restore_points, "get", lambda: None)
    with pytest.raises(TranscriptUnavailable, match="plugin must be on"):
        locate.restore_from_points(fixtures.SOURCE)
