
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import open_files_routes
from src.api.auth import require_auth
from src.core import config_files
from src.core import app_config_guard
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.open_files import open_list, store
from src.core.resource_push.topics import OPEN_FILES, RESOURCE_TOPICS

API = "/api/v1/files/open"
SESSION = "11111111-2222-3333-4444-555555555555"
OTHER = "66666666-7777-8888-9999-000000000000"


def _add_session(state_dir: Path, session_uuid: str, working_dir: str) -> None:
    with closing(connect(db_path_for(state_dir))) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, working_dir, origin, created_at, updated_at) VALUES (?, ?, 'created', '2026-10-12T00:00:00Z', '2026-10-12T00:00:00Z')",
                     (session_uuid, working_dir))


@pytest.fixture
def h(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("print('a')\n")
    (project / "notes.md").write_text("# notes\n")
    _add_session(state, SESSION, str(project))
    _add_session(state, OTHER, str(project))
    home = tmp_path / "claude-home"
    home.mkdir()
    monkeypatch.setattr(config_files, "CLAUDE_HOME", home)
    monkeypatch.setattr(open_files_routes, "_db_path", lambda: db_path_for(state))
    pushed: List[str] = []
    monkeypatch.setattr(open_list.resource_push, "notify", pushed.append)
    open_list.reset_for_test()
    open_list.configure(state)
    app = FastAPI()
    app.include_router(open_files_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    yield SimpleNamespace(client=TestClient(app), state=state, project=project, home=home, pushed=pushed)
    open_list.reset_for_test()


def _open(h, path: str, *, root: str = "workdir", session: str = SESSION, kind: str = "file"):
    return h.client.post(API, json={"root": root, "path": path, "session_uuid": session, "kind": kind})


def test_explicit_path_open_persists_without_session_and_keeps_save_guards(h, tmp_path: Path, monkeypatch):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    target = outside / "note.markdown"
    target.write_text("# first\n")
    opened = h.client.post(f"{API}/path", json={"path": f' "{target}" '})
    assert opened.status_code == 200, opened.text
    row = opened.json()["file"]
    assert (row["root"], row["session_uuid"], row["path"]) == ("absolute", "", str(target.resolve()))
    assert h.client.post(f"{API}/path", json={"path": str(target)}).json()["file"]["id"] == row["id"]
    monkeypatch.setenv("HOME", str(tmp_path))
    assert h.client.post(f"{API}/path", json={"path": "~/elsewhere/note.markdown"}).json()["file"]["id"] == row["id"]
    open_list.configure(h.state)
    assert h.client.get(API).json()["files"][0]["id"] == row["id"]
    url = f"{API}/{row['id']}/content"
    read = h.client.get(url).json()
    assert read["content"] == "# first\n"
    target.write_text("# agent\n")
    assert h.client.put(url, json={"content": "# mine\n", "expected_sha256": read["sha256"]}).status_code == 409
    assert target.read_text() == "# agent\n"
    current = h.client.get(url).json()["sha256"]
    saved = h.client.put(url, json={"content": "# mine\n", "expected_sha256": current})
    assert saved.status_code == 200 and target.read_text() == "# mine\n"
    assert (outside / "note.markdown.bak").read_text() == "# agent\n"


def test_explicit_path_rejects_invalid_roots_and_revalidates_identity(h, tmp_path: Path, monkeypatch):
    target = tmp_path / "outside.md"
    target.write_text("safe")
    for invalid in ("notes.md", str(tmp_path), str(tmp_path / "missing.md"), "\x00"):
        assert h.client.post(f"{API}/path", json={"path": invalid}).status_code in (400, 404, 422)
    loop = tmp_path / "loop.md"
    loop.symlink_to(loop)
    assert h.client.post(f"{API}/path", json={"path": str(loop)}).status_code == 400
    (h.home / "projects").mkdir()
    hidden = h.home / "projects" / "secret.md"
    hidden.write_text("secret")
    assert h.client.post(f"{API}/path", json={"path": str(hidden)}).status_code == 400
    alias = h.home / "plugins"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert h.client.post(f"{API}/path", json={"path": str(alias / "outside.md")}).status_code == 400
    monkeypatch.setattr(app_config_guard, "app_config_path", lambda: target)
    row = h.client.post(f"{API}/path", json={"path": str(target)}).json()["file"]
    url = f"{API}/{row['id']}/content"
    assert h.client.put(url, json={"content": "x", "overwrite": True}).status_code == 409
    target.unlink()
    redirected = tmp_path / "redirected.md"
    redirected.write_text("other")
    target.symlink_to(redirected)
    assert h.client.get(url).json()["reason"] == "unavailable"
    assert h.client.put(url, json={"content": "x", "overwrite": True}).status_code == 400
    assert redirected.read_text() == "other"


def test_explicit_path_keeps_plugin_executable_and_sensitive_guards(h):
    plugins = h.project / "plugins"
    plugins.mkdir()
    readonly = plugins / "entry.md"
    readonly.write_text("text")
    readonly_row = h.client.post(f"{API}/path", json={"path": str(readonly)}).json()["file"]
    readonly_url = f"{API}/{readonly_row['id']}/content"
    assert h.client.get(readonly_url).json()["read_only"] is True
    assert h.client.put(readonly_url, json={"content": "other", "overwrite": True}).status_code == 400

    ordinary_plugins = h.project / "help" / "plugins"
    ordinary_plugins.mkdir(parents=True)
    guide = ordinary_plugins / "index.md"
    guide.write_text("help")
    guide_row = h.client.post(f"{API}/path", json={"path": str(guide)}).json()["file"]
    guide_url = f"{API}/{guide_row['id']}/content"
    assert h.client.get(guide_url).json()["read_only"] is False
    assert h.client.put(guide_url, json={"content": "updated", "overwrite": True}).status_code == 200

    scripts = h.project / "scripts"
    scripts.mkdir()
    executable = scripts / "hook.py"
    executable.write_text("print('ok')")
    executable_row = h.client.post(f"{API}/path", json={"path": str(executable)}).json()["file"]
    executable_url = f"{API}/{executable_row['id']}/content"
    assert h.client.get(executable_url).json()["is_executable"] is True
    assert h.client.put(executable_url, json={"content": "print('new')", "overwrite": True}).status_code == 400

    secret = h.project / ".env.local"
    secret.write_text("placeholder")
    secret_row = h.client.post(f"{API}/path", json={"path": str(secret)}).json()["file"]
    secret_url = f"{API}/{secret_row['id']}/content"
    assert h.client.get(secret_url).json()["is_sensitive"] is True
    assert h.client.put(secret_url, json={"content": "replacement", "overwrite": True}).status_code == 400


def test_the_topic_is_advertised():
    assert OPEN_FILES in RESOURCE_TOPICS


def test_open_mints_an_id_and_a_second_open_reuses_the_row(h):
    first = _open(h, "src/a.py")
    assert first.status_code == 200, first.text
    row = first.json()["file"]
    assert len(row["id"]) == 16 and int(row["id"], 16) >= 0
    assert (row["title"], row["path"], row["root"], row["session_uuid"]) == ("a.py", "src/a.py", "workdir", SESSION)
    assert first.json()["reused"] is False
    again = _open(h, "/src/a.py/".strip("/"))
    assert again.json()["reused"] is True and again.json()["file"]["id"] == row["id"]
    assert again.json()["file"]["seq"] > row["seq"]
    listed = h.client.get(API).json()["files"]
    assert [f["id"] for f in listed] == [row["id"]]
    assert h.pushed == [OPEN_FILES, OPEN_FILES]


def test_the_same_file_from_another_session_is_its_own_row(h):
    mine = _open(h, "notes.md").json()["file"]
    theirs = _open(h, "notes.md", session=OTHER).json()["file"]
    assert mine["id"] != theirs["id"]
    only_mine = h.client.get(API, params={"session_uuid": SESSION}).json()["files"]
    assert [f["id"] for f in only_mine] == [mine["id"]]


def test_close_removes_the_row_and_names_the_topic(h):
    row = _open(h, "notes.md").json()["file"]
    h.pushed.clear()
    assert h.client.delete(f"{API}/{row['id']}").status_code == 204
    assert h.client.get(API).json()["files"] == []
    assert h.pushed == [OPEN_FILES]
    assert h.client.delete(f"{API}/{row['id']}").status_code == 404
    assert h.pushed == [OPEN_FILES]


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", "/etc/hosts", "C:\\x"])
def test_a_path_leaving_the_root_is_refused(h, path):
    (h.project.parent / "outside.txt").write_text("secret")
    answer = _open(h, path)
    assert answer.status_code in (400, 404), answer.text
    assert h.client.get(API).json()["files"] == [] and h.pushed == []


def test_a_symlink_out_of_the_folder_is_refused(h):
    (h.project.parent / "outside.txt").write_text("secret")
    (h.project / "link.txt").symlink_to(h.project.parent / "outside.txt")
    answer = _open(h, "link.txt")
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "open_file_path_refused"


def test_a_folder_a_missing_file_and_an_unknown_session_are_refused(h):
    assert _open(h, "src").json()["detail"]["code"] == "open_file_not_found"
    assert _open(h, "nope.txt").json()["detail"]["code"] == "open_file_not_found"
    assert _open(h, "notes.md", session="no-such-session").status_code == 404
    assert _open(h, "notes.md", session="no-such-session").json()["detail"]["code"] == "open_file_session_not_found"
    assert h.client.post(API, json={"root": "workdir", "path": "notes.md", "session_uuid": SESSION,
                                    "project_path": "/etc"}).status_code == 422


def test_a_read_answers_the_sha256_of_the_bytes_on_disk(h):
    row = _open(h, "src/a.py").json()["file"]
    body = h.client.get(f"{API}/{row['id']}/content").json()
    raw = (h.project / "src" / "a.py").read_bytes()
    assert body["viewable"] is True and body["content"] == raw.decode()
    assert body["sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["mtime_ns"] == (h.project / "src" / "a.py").stat().st_mtime_ns and body["size"] == len(raw)


def test_a_save_on_the_read_revision_lands_and_answers_the_new_one(h):
    row = _open(h, "notes.md").json()["file"]
    base = h.client.get(f"{API}/{row['id']}/content").json()["sha256"]
    saved = h.client.put(f"{API}/{row['id']}/content", json={"content": "# new\n", "expected_sha256": base})
    assert saved.status_code == 200, saved.text
    assert (h.project / "notes.md").read_text() == "# new\n"
    assert saved.json()["sha256"] == hashlib.sha256(b"# new\n").hexdigest() and saved.json()["backed_up"] is True
    again = h.client.put(f"{API}/{row['id']}/content", json={"content": "# newer\n", "expected_sha256": saved.json()["sha256"]})
    assert again.status_code == 200


def test_a_stale_save_is_refused_with_409_and_overwrite_is_the_way_past(h):
    row = _open(h, "notes.md").json()["file"]
    base = h.client.get(f"{API}/{row['id']}/content").json()["sha256"]
    (h.project / "notes.md").write_text("# an agent edited this\n")
    stale = h.client.put(f"{API}/{row['id']}/content", json={"content": "# mine\n", "expected_sha256": base})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "file_changed_on_disk"
    assert detail["sha256"] == hashlib.sha256(b"# an agent edited this\n").hexdigest()
    assert (h.project / "notes.md").read_text() == "# an agent edited this\n"
    no_base = h.client.put(f"{API}/{row['id']}/content", json={"content": "# mine\n"})
    assert no_base.status_code == 422
    forced = h.client.put(f"{API}/{row['id']}/content", json={"content": "# mine\n", "overwrite": True})
    assert forced.status_code == 200 and (h.project / "notes.md").read_text() == "# mine\n"


def test_a_save_after_the_file_was_deleted_is_stale_too(h):
    row = _open(h, "notes.md").json()["file"]
    base = h.client.get(f"{API}/{row['id']}/content").json()["sha256"]
    (h.project / "notes.md").unlink()
    stale = h.client.put(f"{API}/{row['id']}/content", json={"content": "x", "expected_sha256": base})
    assert stale.status_code == 409 and stale.json()["detail"]["sha256"] is None
    assert not (h.project / "notes.md").exists()


def test_a_binary_and_an_oversized_file_open_and_answer_the_cant_show_view(h, monkeypatch):
    (h.project / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    (h.project / "big.log").write_text("x" * 64)
    monkeypatch.setattr(config_files, "MAX_READ_BYTES", 32)
    png = _open(h, "logo.png").json()["file"]
    big = _open(h, "big.log").json()["file"]
    assert h.client.get(f"{API}/{png['id']}/content").json() == {
        "id": png["id"], "viewable": False, "reason": "not_text", "detail": "file is not text/utf-8 - not editable here"}
    assert h.client.get(f"{API}/{big['id']}/content").json()["reason"] == "too_large"


def test_a_gone_file_and_a_gone_session_answer_instead_of_crashing(h):
    row = _open(h, "notes.md").json()["file"]
    (h.project / "notes.md").unlink()
    assert h.client.get(f"{API}/{row['id']}/content").json()["reason"] == "gone"
    with closing(sqlite3.connect(db_path_for(h.state))) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE session_uuid = ?", (SESSION,))
    assert h.client.get(f"{API}/{row['id']}/content").json()["reason"] == "unavailable"
    saved = h.client.put(f"{API}/{row['id']}/content", json={"content": "x", "overwrite": True})
    assert saved.status_code == 409 and saved.json()["detail"]["code"] == "open_file_unavailable"


def test_a_diff_row_is_read_only_and_names_the_session_folder(h):
    diff = _open(h, "src/a.py", kind="diff").json()["file"]
    assert diff["kind"] == "diff"
    assert _open(h, "src/a.py").json()["file"]["id"] != diff["id"]
    assert h.client.get(f"{API}/{diff['id']}/content").json()["detail"]["code"] == "open_file_is_diff"
    saved = h.client.put(f"{API}/{diff['id']}/content", json={"content": "x", "overwrite": True})
    assert saved.status_code == 400 and (h.project / "src" / "a.py").read_text() == "print('a')\n"
    assert _open(h, "settings.json", root="user", kind="diff").json()["detail"]["code"] == "open_file_path_refused"
    assert _open(h, "../x", kind="diff").status_code == 400


def test_a_user_root_file_opens_from_a_session_and_saves(h):
    (h.home / "CLAUDE.md").write_text("rules\n")
    row = _open(h, "CLAUDE.md", root="user").json()["file"]
    body = h.client.get(f"{API}/{row['id']}/content").json()
    assert body["content"] == "rules\n"
    saved = h.client.put(f"{API}/{row['id']}/content", json={"content": "more\n", "expected_sha256": body["sha256"]})
    assert saved.status_code == 200 and (h.home / "CLAUDE.md").read_text() == "more\n"


def test_rows_come_back_after_a_restart_and_a_corrupt_file_is_moved_aside(h):
    first = _open(h, "notes.md").json()["file"]
    second = _open(h, "src/a.py").json()["file"]
    open_list.reset_for_test()
    open_list.configure(h.state)
    assert [f["id"] for f in h.client.get(API).json()["files"]] == [first["id"], second["id"]]
    assert _open(h, "notes.md").json()["file"]["id"] == first["id"]
    target = store.path_in(h.state)
    good = json.loads(target.read_text())["files"][0]
    target.write_text(json.dumps({"version": 1, "files": [good, {"id": "x"}, dict(good, id="z" * 16)]}))
    open_list.reset_for_test()
    open_list.configure(h.state)
    assert [f.id for f in open_list.listing()] == [good["id"]]
    target.write_text("{not json")
    open_list.configure(h.state)
    assert open_list.listing() == [] and len(list(h.state.glob("open_files.json.corrupt-*"))) == 1


def test_the_list_is_capped_by_dropping_the_least_recently_opened(h, monkeypatch):
    monkeypatch.setattr(open_list, "MAX_FILES", 2)
    a = _open(h, "notes.md").json()["file"]
    b = _open(h, "src/a.py").json()["file"]
    _open(h, "notes.md")
    c = _open(h, "src/a.py", kind="diff").json()["file"]
    assert [f["id"] for f in h.client.get(API).json()["files"]] == [a["id"], c["id"]]
    assert b["id"] not in {f["id"] for f in h.client.get(API).json()["files"]}
