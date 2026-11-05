
from __future__ import annotations

import hashlib
import os
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import open_files_routes
from src.core.db import connect, db_path_for
from tests.python.open_files.test_open_files_routes import API, SESSION, _open, h  # noqa: F401

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


def _id(response) -> str:
    return response.json()["file"]["id"]


def test_text_file_bytes_and_sha256_match(h):  # noqa: F811
    body = ("héllo\r\n  trailing  \n" * 50).encode()
    (h.project / "t.txt").write_bytes(body)
    got = h.client.get(f"{API}/{_id(_open(h, 't.txt'))}/download")
    assert got.status_code == 200
    assert hashlib.sha256(got.content).hexdigest() == hashlib.sha256(body).hexdigest()
    assert got.headers["content-type"].startswith("text/plain")
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["content-disposition"].startswith("attachment;")


def test_png_bytes_equal_and_media_type(h):  # noqa: F811
    (h.project / "p.png").write_bytes(PNG_BYTES)
    got = h.client.get(f"{API}/{_id(_open(h, 'p.png'))}/download")
    assert got.status_code == 200
    assert got.content == PNG_BYTES
    assert got.headers["content-type"] == "image/png"


def test_unknown_extension_is_octet_stream_and_large_file_is_whole(h):  # noqa: F811
    big = os.urandom(3 * 1024 * 1024)
    (h.project / "blob.zzzunknown").write_bytes(big)
    got = h.client.get(f"{API}/{_id(_open(h, 'blob.zzzunknown'))}/download")
    assert got.status_code == 200 and got.content == big
    assert got.headers["content-type"] == "application/octet-stream"


def test_non_ascii_filename_has_utf8_and_ascii_forms(h):  # noqa: F811
    name = 'résumé "v2" ✓.txt'
    (h.project / name).write_text("x")
    header = h.client.get(f"{API}/{_id(_open(h, name))}/download").headers["content-disposition"]
    assert f"filename*=UTF-8''{quote(name, safe='')}" in header
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback.isascii() and '"' not in fallback and "\\" not in fallback and fallback.endswith(".txt")


def test_diff_row_is_refused_400(h):  # noqa: F811
    row = _open(h, "src/a.py", kind="diff")
    got = h.client.get(f"{API}/{_id(row)}/download")
    assert got.status_code == 400 and got.json()["detail"]["code"] == "open_file_is_diff"


def test_unknown_id_is_404(h):  # noqa: F811
    got = h.client.get(f"{API}/0123456789abcdef/download")
    assert got.status_code == 404 and got.json()["detail"]["code"] == "open_file_not_found"


def _refused_as(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def test_deleted_file_is_404_with_the_routes_own_code(h):  # noqa: F811
    file_id = _id(_open(h, "notes.md"))
    assert h.client.get(f"{API}/{file_id}/download").status_code == 200
    (h.project / "notes.md").unlink()
    _refused_as(h.client.get(f"{API}/{file_id}/download"), 404, "open_file_not_found")


def test_symlink_swapped_in_is_refused(h, tmp_path: Path):  # noqa: F811
    file_id = _id(_open(h, "notes.md"))
    assert h.client.get(f"{API}/{file_id}/download").status_code == 200
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (h.project / "notes.md").unlink()
    (h.project / "notes.md").symlink_to(outside)
    got = h.client.get(f"{API}/{file_id}/download")
    _refused_as(got, 404, "open_file_not_found")
    assert b"secret" not in got.content


def test_fifo_is_refused_and_never_hangs(h):  # noqa: F811
    file_id = _id(_open(h, "notes.md"))
    assert h.client.get(f"{API}/{file_id}/download").status_code == 200
    (h.project / "notes.md").unlink()
    os.mkfifo(h.project / "notes.md")
    _refused_as(h.client.get(f"{API}/{file_id}/download"), 404, "open_file_not_found")


def test_gone_session_is_409_open_file_unavailable(h):  # noqa: F811
    file_id = _id(_open(h, "notes.md"))
    with closing(connect(db_path_for(h.state))) as conn:
        conn.execute("DELETE FROM sessions WHERE session_uuid = ?", (SESSION,))
    _refused_as(h.client.get(f"{API}/{file_id}/download"), 409, "open_file_unavailable")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_permission_refusal_reports_its_reason_not_gone(h):  # noqa: F811
    file_id = _id(_open(h, "notes.md"))
    (h.project / "notes.md").chmod(0)
    try:
        got = h.client.get(f"{API}/{file_id}/download")
    finally:
        (h.project / "notes.md").chmod(0o644)
    _refused_as(got, 403, "open_file_unreadable")
    assert "no longer there" not in got.json()["detail"]["detail"]


def test_content_length_matches_the_file(h):  # noqa: F811
    body = os.urandom(300_000)
    (h.project / "c.bin").write_bytes(body)
    got = h.client.get(f"{API}/{_id(_open(h, 'c.bin'))}/download")
    assert got.headers["content-length"] == str(len(body)) and got.content == body


def test_unauthenticated_is_refused():
    app = FastAPI()
    app.include_router(open_files_routes.router, prefix="/api/v1")
    assert TestClient(app).get(f"{API}/0123456789abcdef/download").status_code in (401, 403)
