
from __future__ import annotations

import pytest

from src.cplugs.reviewboard import attachment_guard, attachment_types
from src.cplugs.reviewboard.errors import FileTypeRefused
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_store
from tests.python.cplugs.reviewboard.test_attachments import MD, PDF, b64, board, client, env, sidecar, tree  # noqa: F401


def post(client, board: dict, name: str, data: bytes):
    return client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": name, "content_base64": b64(data)}]})


@pytest.mark.parametrize("name,data,reason", [
    ("run.sh", b"#!/bin/sh\nrm -rf /\n", "extension_not_allowed"),
    ("movie.avi", b"RIFF....AVI ", "extension_not_allowed"),
    ("song.ogg", b"OggS", "extension_not_allowed"),
    ("tool.exe", b"MZ\x90\x00", "extension_not_allowed"),
    ("bundle.zip", b"PK\x03\x04", "extension_not_allowed"),
    ("README", b"no extension", "no_extension"),
    (".md", b"a dotfile is not an extension", "no_extension"),
    ("fake.pdf", b"this is not a pdf", "content_mismatch"),
    ("fake.docx", b"%PDF-1.4 not a zip", "content_mismatch"),
    ("blob.md", b"# title\x00\x01\x02 binary", "not_utf8"),
    ("tool.mp4", b"MZ\x90\x00\x03\x00\x00\x00 a renamed exe", "content_mismatch"),
    ("clip.mov", b"\x00\x00\x00\x14moov0000", "content_mismatch"),
    ("clip.webm", b"\x1a\x45\xdf\xa2 one byte off", "content_mismatch"),
    ("song.mp3", b"\xff\x1b\x90\x00 sync bits wrong", "content_mismatch"),
    ("sound.wav", b"RIFF\x00\x00\x00\x00AVI LIST", "content_mismatch"),
    ("empty.mp3", b"\xff", "content_mismatch"),
    ("latin.txt", "caf\xe9".encode("latin-1"), "not_utf8"),
])
def test_the_route_refuses_a_file_off_the_allow_list_and_stores_nothing(env, client, board, name, data, reason):
    """A file off the allow-list, or lying about its type, answers 415 with its reason and leaves no file, info or index entry."""
    before, thread = tree(env.root), task_manager_store(env).item(board["item"])["thread"]
    r = post(client, board, name, data)
    assert r.status_code == 415, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "reviewboard_file_type_refused" and detail["reason"] == reason and detail["file"] == name.lstrip(".")
    assert tree(env.root) == before and task_manager_store(env).item(board["item"])["thread"] == thread
    assert "attachments" not in sidecar(env, board["slug"]).get("ext", {})


def test_a_text_file_that_is_not_utf8_says_so_in_plain_words(env, client, board):
    r = post(client, board, "data.csv", "caf\xe9,1\n".encode("latin-1"))
    assert r.status_code == 415, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "not_utf8" and "not UTF-8 text" in detail["detail"] and "not a real" not in detail["detail"]


def test_one_bad_file_refuses_the_whole_attach(env, client, board):
    before = tree(env.root)
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments",
                    json={"files": [{"name": "ok.md", "content_base64": b64(MD)}, {"name": "run.sh", "content_base64": b64(b"ls")}]})
    assert r.status_code == 415 and tree(env.root) == before


def test_the_mcp_door_refuses_the_same_file(env, board):
    ok, text = env.call("task_manager_board_attachment_add", {"board": board["slug"], "files": [{"name": "run.sh", "content_base64": b64(b"ls")}]})
    assert not ok and "reviewboard_file_type_refused" in text, text


def test_an_allowed_type_with_matching_bytes_still_attaches(env, client, board):
    for name, data in (("spec.PDF", PDF), ("notes.md", MD), ("data.json", b'{"a": 1}'), ("sheet.csv", b"a,b\n1,2\n")):
        assert post(client, board, name, data).status_code == 200, name


def test_every_allowed_extension_has_a_class_and_the_guard_returns_it():
    assert attachment_types.ALLOWED_EXTENSIONS == frozenset(attachment_types.CLASS_BY_EXTENSION)
    assert attachment_guard.check_type("a.md", b"x") == attachment_types.TEXT
    assert attachment_guard.check_type("a.docx", b"PK\x03\x04rest") == attachment_types.OFFICE
    assert attachment_guard.extension_of("Spec.PDF") == ".pdf" and attachment_guard.extension_of(".md") == ""
    with pytest.raises(FileTypeRefused):
        attachment_guard.check_type("a.exe", b"x")


MEDIA = {
    "clip.mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
    "clip.MOV": b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  ",
    "clip.webm": b"\x1a\x45\xdf\xa3\x9fB\x86\x81\x01",
    "song.mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00",
    "frames.mp3": b"\xff\xfb\x90\x64\x00\x00\x00\x00",
    "sound.wav": b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00",
}
WEB = {
    "page.html": b"<!doctype html><title>x</title><p>hi</p>",
    "page.htm": b"<html><body>old school</body></html>",
    "logo.svg": b"<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>",
    "site.css": b"body { color: #333; }\n",
    "app.js": b"export const answer = 42;\n",
}


def test_web_code_and_media_types_attach_with_real_headers(env, client, board):
    files = {**WEB, **MEDIA}
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": n, "content_base64": b64(d)} for n, d in list(files.items())[:10]]})
    assert r.status_code == 200, r.text
    listed = r.json()["attachments"]
    assert [a["name"] for a in listed] == list(files)[:10]
    for row, data in zip(listed, list(files.values())[:10]):
        assert client.get(row["url"]).content == data


def test_web_and_media_extensions_have_the_classes_the_guard_judges_them_by():
    for ext in (".html", ".htm", ".svg", ".css", ".js"):
        assert attachment_types.CLASS_BY_EXTENSION[ext] == attachment_types.TEXT
    for ext in (".mp4", ".mov", ".webm", ".mp3", ".wav"):
        assert attachment_types.CLASS_BY_EXTENSION[ext] == attachment_types.MEDIA
