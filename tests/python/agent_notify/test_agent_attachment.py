
from __future__ import annotations

import os
import stat
import struct
import zlib

import pytest

from src.core.notifications import agent_message
from src.core.notifications.sources import toast as toast_source
from src.core.notify_media import intake, store
from tests.python.agent_notify.test_agent_notify import _h, _tool, env  # noqa: F401

SECRET = "ghp_" + "Kx9mQ2vL7pRt4WzN8bYc3JdF6hGs1AeUoXiP"


@pytest.fixture
def rig(env, monkeypatch, tmp_path):  # noqa: F811
    client, mgr, _, _ = env
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(store, "media_dir", lambda: _dir(tmp_path / "media"))
    monkeypatch.setattr(agent_message, "session_roots", lambda m, s: [str(project)])
    hints = []
    plain = mgr.record_toast

    def record(*a, **kw):
        hints.append(toast_source.CARD_HINT.get())
        return plain(*a, **kw)
    monkeypatch.setattr(mgr, "record_toast", record)
    return client, mgr, project, hints


def _dir(path):
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _png() -> bytes:
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 3, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00" * 3 * 3)) + chunk(b"IEND", b""))


def _send(client, mgr, attachment, text="here"):
    return client.post("/api/v1/sessions/ses_a/agent-message", json={"text": text, "attachment": attachment}, headers=_h(mgr))


def test_in_project_image_is_stored_0600_and_reaches_card_hint(rig, tmp_path):
    client, mgr, project, hints = rig
    (project / "shot.png").write_bytes(_png())
    r = _send(client, mgr, {"path": str(project / "shot.png")})
    assert r.status_code == 201, r.text
    media = hints[0]["media"]
    assert media["kind"] == "image" and media["mime"] == "image/png" and media["name"] == "shot.png" and media["caption"] == "here"
    entry = store.entry(media["id"])
    assert entry.path.read_bytes() == _png() and not entry.path.is_symlink()
    assert stat.S_IMODE(entry.path.stat().st_mode) == 0o600 and stat.S_IMODE(entry.path.parent.stat().st_mode) == 0o700


def test_kind_comes_from_the_bytes_not_the_name(rig):
    client, mgr, project, hints = rig
    (project / "notes.txt").write_bytes(_png())
    (project / "clip.png").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\0" * 32)
    (project / "readme.md").write_text("plain notes")
    for name in ("notes.txt", "clip.png", "readme.md"):
        assert _send(client, mgr, {"path": str(project / name)}).status_code == 201
        client.app.state.session_manager  # noqa: B018
        agent_message._LIMITER.__init__()
    assert [h["media"]["kind"] for h in hints] == ["image", "video", "file"]


def test_outside_project_and_symlink_escape_are_422(rig, tmp_path):
    client, mgr, project, hints = rig
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    (project / "link.txt").symlink_to(outside)
    for path in (outside, project / "link.txt", project / ".." / "outside.txt"):
        r = _send(client, mgr, {"path": str(path)})
        assert r.status_code == 422 and "outside_project" in r.text, r.text
        agent_message._LIMITER.__init__()
    assert hints == [] and not (tmp_path / "media").exists()


def test_not_a_regular_file_is_422(rig):
    client, mgr, project, _ = rig
    os.mkfifo(project / "pipe")
    assert _send(client, mgr, {"path": str(project / "pipe")}).status_code == 422


def test_oversize_is_413(rig, monkeypatch):
    client, mgr, project, hints = rig
    monkeypatch.setitem(store.MAX_BYTES, "file", 1024)
    (project / "big.bin").write_bytes(b"\x01" * 2048)
    r = _send(client, mgr, {"path": str(project / "big.bin")})
    assert r.status_code == 413 and "too_large" in r.text and hints == []


def test_http_url_is_422_and_https_link_reaches_card_hint(rig):
    client, mgr, _, hints = rig
    assert _send(client, mgr, {"url": "http://example.com/x"}).status_code == 422
    assert _send(client, mgr, {"url": "https://example.com/" + "a" * 2000}).status_code == 422
    assert _send(client, mgr, {"url": "https://example.com/pr/7", "title": "t" * 121}).status_code == 422
    agent_message._LIMITER.__init__()
    assert _send(client, mgr, {"url": "https://example.com/pr/7", "title": "PR 7"}).status_code == 201
    assert hints[-1] == {"url": "https://example.com/pr/7", "title": "PR 7"}


def test_secret_in_a_text_file_is_422_and_the_value_is_never_logged(rig, capfd):
    client, mgr, project, hints = rig
    (project / ".env").write_text(f"TOKEN={SECRET}\n")
    r = _send(client, mgr, {"path": str(project / ".env")})
    assert r.status_code == 422 and "secret_found" in r.text
    out = capfd.readouterr()
    assert SECRET not in r.text and SECRET not in out.out + out.err and hints == []
    (project / "ok.txt").write_text("nothing secret here")
    assert _send(client, mgr, {"path": str(project / "ok.txt")}).status_code == 201


def test_tool_takes_attachment_and_schema_documents_it(rig):
    client, mgr, project, hints = rig
    (project / "a.png").write_bytes(_png())
    res = client.post("/mcp", json=_rpc_call({"text": "x", "attachment": {"path": str(project / "a.png")}}), headers=_h(mgr)).json()["result"]
    assert not res.get("isError") and hints[0]["media"]["kind"] == "image"
    from src.core.mcp.notify_tools import WRITE_TOOLS
    assert "attachment" in WRITE_TOOLS["notify"][1]


def _rpc_call(args):
    from tests.python.mcp.test_mcp_endpoint import _rpc
    return _rpc("tools/call", {"name": "notify", "arguments": args})


def test_prune_drops_old_and_oldest_past_the_total(rig, monkeypatch):
    _, _, project, _ = rig
    old = store.write("file", b"old", "text/plain")
    new = store.write("file", b"new", "text/plain")
    for p in store.media_dir().glob(f"{old.media_id}*"):
        os.utime(p, (1, 1))
    assert store.prune() == 2 and store.entry(old.media_id) is None and store.entry(new.media_id)
    monkeypatch.setattr(store, "TOTAL_MAX_BYTES", 4)
    assert store.prune() >= 1 and store.entry(new.media_id) is None


def test_pdf_page_count_is_read_and_absent_when_unreadable(rig):
    client, mgr, project, hints = rig
    page = b"<< /Type /Page /Parent 2 0 R >>"
    (project / "a.pdf").write_bytes(b"%PDF-1.4\n2 0 obj<< /Kids [3 0 R 4 0 R] /Type /Pages /Count 2 >>endobj\n" + page * 2)
    (project / "b.pdf").write_bytes(b"%PDF-1.5\nstream\x00\x01 compressed \x02")
    for name in ("a.pdf", "b.pdf"):
        assert _send(client, mgr, {"path": str(project / name)}).status_code == 201
        agent_message._LIMITER.__init__()
    assert hints[0]["media"]["pages"] == 2 and "pages" not in hints[1]["media"]
