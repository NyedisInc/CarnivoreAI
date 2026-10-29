
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.config.uploads import UploadsConfig
from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle import board_port, routes as huddle_routes
from src.cplugs.sdk import uploads as sdk_uploads
from tests.python.cplugs.reviewboard.harness import BASE, PANE, Env, huddle_on, huddle_store, make_env

TOKEN = AgentCaller("mcp-token:7", "mcp-token:7", "mcp-token:7", token_name="phone", scope="write")
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
MD = b"# spec\n\n- one\n- two\n"
HTML = "<!doctype html><title>bar</title><p>bar</p>"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Env:
    monkeypatch.setattr(sdk_uploads, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(uploads=UploadsConfig())))
    made = make_env(tmp_path)
    made.app.include_router(huddle_routes.router, prefix="/api/v1")
    huddle_on(made, monkeypatch)
    yield made
    board_port.unregister()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


@pytest.fixture
def board(env: Env, client) -> dict:
    item = huddle_store(env).add("12", "redo the bottom bar", actor="claude", title="bottom bar task")["id"]
    r = client.post(f"{BASE}/boards", json={"slug_name": "bottom-bar", "title": "bottom bar", "task": {"item_id": item}, "summary": "first",
                                            "html": HTML, "viewport": 320, "request_review": False})
    assert r.status_code == 200, r.text
    return {"slug": r.json()["slug"], "item": item}


def sidecar(env: Env, slug: str) -> dict:
    return json.loads((env.board(slug) / "sidecar.json").read_text())


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_pane_attaches_a_pdf_and_an_md_file_and_each_opens_to_its_exact_bytes(env: Env, client, board, tmp_path: Path):
    (tmp_path / "spec.pdf").write_bytes(PDF)
    (tmp_path / "notes.md").write_bytes(MD)
    notes = lambda: [m for m in huddle_store(env).item(board["item"])["thread"] if m.get("category") != "status"]
    thread_before = len(notes())
    published_before = len(env.published)
    ok, answer = env.call("task_manager_board_attachment_add", {"board": board["slug"], "note": "the spec and my notes",
                                                                 "file_paths": [str(tmp_path / "spec.pdf"), str(tmp_path / "notes.md")]})
    assert ok, answer
    row = huddle_store(env).item(board["item"])
    added = notes()[thread_before:]
    assert len(added) == 1, added
    info = added[0]
    assert info["author"] == "claude" and info["kind"] == "info" and info["id"] == answer["message_id"]
    assert info["text"].startswith("attached to board bottom bar: spec.pdf, notes.md") and "the spec and my notes" in info["text"]
    assert [f["name"] for f in info["files"]] == ["spec.pdf", "notes.md"]
    assert answer["review"]["moved"] is True and row["state"] == "review"
    index = sidecar(env, board["slug"])["ext"]["attachments"]
    assert index["v"] == 1 and [e["name"] for e in index["files"]] == ["spec.pdf", "notes.md"]
    for entry, data in zip(index["files"], (PDF, MD)):
        assert entry["sha256"] == hashlib.sha256(data).hexdigest() and entry["bytes"] == len(data)
        assert entry["item_id"] == board["item"] and entry["message_id"] == answer["message_id"] and entry["revision"] == "r1"
    assert [e["file_id"] for e in index["files"]] == [f["id"] for f in info["files"]]
    assert [t for t in env.published[published_before:] if t.startswith("cplug.reviewboard.")] == ["cplug.reviewboard.boards"]
    listed = client.get(f"{BASE}/boards/{board['slug']}/attachments")
    assert listed.status_code == 200, listed.text
    rows = listed.json()["attachments"]
    assert listed.json()["slug"] == board["slug"] and [r["name"] for r in rows] == ["spec.pdf", "notes.md"]
    assert rows == answer["attachments"]
    for row_, data in zip(rows, (PDF, MD)):
        assert row_["url"] == f"/api/v1/cplugs/huddle/items/{board['item']}/files/{row_['file_id']}"
        served = client.get(row_["url"])
        assert served.status_code == 200 and served.content == data


def test_the_route_attaches_inline_files_and_a_second_attach_appends(env: Env, client, board):
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)}],
                                                                       "request_review": False})
    assert r.status_code == 200, r.text
    assert r.json()["review"]["requested"] is False and huddle_store(env).item(board["item"])["state"] != "review"
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "../b.pdf", "content_base64": b64(PDF)}]})
    assert r.status_code == 200, r.text
    assert [e["name"] for e in sidecar(env, board["slug"])["ext"]["attachments"]["files"]] == ["a.md", "b.pdf"]
    assert client.get(r.json()["attachments"][0]["url"]).content == PDF


def test_a_tokens_file_paths_are_refused_and_nothing_is_stored(env: Env, board, tmp_path: Path):
    (tmp_path / "spec.pdf").write_bytes(PDF)
    thread_before = huddle_store(env).item(board["item"])["thread"]
    before = sidecar(env, board["slug"])
    ok, text = env.call("task_manager_board_attachment_add", {"board": board["slug"], "file_paths": [str(tmp_path / "spec.pdf")]}, TOKEN)
    assert not ok and "only a session running here" in text, text
    assert sidecar(env, board["slug"]) == before and huddle_store(env).item(board["item"])["thread"] == thread_before


def test_a_refused_file_leaves_nothing_behind(env: Env, client, board):
    before, thread_before = tree(env.root), huddle_store(env).item(board["item"])["thread"]
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments",
                    json={"files": [{"name": "ok.md", "content_base64": b64(MD)}, {"name": "fake.png", "content_base64": b64(b"not a png")}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reviewboard_invalid", r.text
    assert tree(env.root) == before and huddle_store(env).item(board["item"])["thread"] == thread_before


def test_a_scratch_board_refuses_an_attachment(env: Env, client):
    ok, posted = env.call("task_manager_scratch_post", {"name": "phone", "html": HTML})
    assert ok, posted
    r = client.post(f"{BASE}/boards/{posted['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_scratch_board", r.text
    ok, text = env.call("task_manager_board_attachment_add", {"board": posted["slug"], "files": [{"name": "a.md", "content_base64": b64(MD)}]})
    assert not ok and "reviewboard_scratch_board" in text


def test_a_missing_board_is_404(env: Env, client):
    assert client.get(f"{BASE}/boards/20261014-nope/attachments").json()["detail"]["code"] == "reviewboard_not_found"
    r = client.post(f"{BASE}/boards/20261014-nope/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)}]})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "reviewboard_not_found"
    ok, text = env.call("task_manager_board_attachment_add", {"board": "20261014-nope", "files": [{"name": "a.md", "content_base64": b64(MD)}]})
    assert not ok and "reviewboard_not_found" in text


def huddle_files(env: Env) -> dict:
    base = env.host.storage("huddle").path / "files"
    return tree(base) if base.is_dir() else {}


def test_a_note_the_huddle_would_refuse_is_refused_first_and_a_crlf_note_is_mended(env: Env, client, board):
    before, thread_before, files_before = sidecar(env, board["slug"]), huddle_store(env).item(board["item"])["thread"], huddle_files(env)
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)}],
                                                                       "note": "a bell \x07 here"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reviewboard_invalid", r.text
    assert sidecar(env, board["slug"]) == before and huddle_files(env) == files_before
    assert huddle_store(env).item(board["item"])["thread"] == thread_before
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)}],
                                                                       "note": "line one\r\nline two", "request_review": False})
    assert r.status_code == 200, r.text
    assert huddle_store(env).item(board["item"])["thread"][-1]["text"].endswith("line one\nline two")


def test_a_huddle_refusal_after_the_files_are_saved_removes_them_and_answers_a_board_refusal(env: Env, client, board, monkeypatch):
    from src.cplugs.huddle.rules import TaskManagerForbidden
    from src.cplugs.huddle.store import TaskManagerStore

    def refuse(self, *args, **kwargs):
        raise TaskManagerForbidden("the item is settled")

    monkeypatch.setattr(TaskManagerStore, "post", refuse)
    before, files_before = sidecar(env, board["slug"]), huddle_files(env)
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)},
                                                                                 {"name": "b.pdf", "content_base64": b64(PDF)}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_task_manager_refused", r.text
    assert r.json()["detail"]["task_code"] == "task_manager_forbidden"
    assert sidecar(env, board["slug"]) == before and huddle_files(env) == files_before
    ok, text = env.call("task_manager_board_attachment_add", {"board": board["slug"], "files": [{"name": "a.md", "content_base64": b64(MD)}]})
    assert not ok and "reviewboard_task_manager_refused" in text and huddle_files(env) == files_before


def test_a_non_string_file_body_is_a_422_not_a_crash(env: Env, client, board):
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": 5}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reviewboard_invalid", r.text


def test_an_index_write_that_fails_after_the_post_is_a_success_that_says_so(env: Env, client, board, monkeypatch):
    from src.cplugs.reviewboard import attachments

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(attachments, "_index", broken)
    published_before = len(env.published)
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "a.md", "content_base64": b64(MD)}],
                                                                       "request_review": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["indexed"] is False and body["etag"] is None and str(body["message_id"]) in body["warning"]
    assert client.get(body["attachments"][0]["url"]).content == MD
    assert "cplug.reviewboard.boards" in env.published[published_before:]
    assert MD in huddle_files(env).values()


def test_an_index_entry_whose_file_id_is_not_8_hex_is_left_out():
    from src.cplugs.reviewboard import attachments

    good = {"file_id": "49759e95", "item_id": 7, "message_id": 41, "name": "a.md", "mime": "text/markdown", "bytes": 3,
            "sha256": "a" * 64, "added_at": "2026-10-14T09:05:00Z", "revision": "r1"}
    forged = {**good, "file_id": "%2e%2e/%2e%2e/sessions"}
    listed = attachments.entries_of({"ext": {"attachments": {"v": 1, "files": [good, forged]}}})
    assert [e["file_id"] for e in listed] == ["49759e95"]
    with pytest.raises(ValueError):
        board_port.BoardPort(SimpleNamespace()).file_url(7, "../x")
