from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_uv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_uv_logs_"))

from src.api.auth import require_auth  # noqa: E402
from src.api.session_upload_view_routes import router  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


@pytest.fixture
def served(tmp_path):
    bucket = tmp_path / ".cloude_uploads"
    bucket.mkdir()
    (bucket / "ab12cd34-a.png").write_bytes(PNG)
    (bucket / "ab12cd34-n.txt").write_text("hi")
    (bucket / "ab12cd34-x.svg").write_text("<svg/>")
    (tmp_path / "secret.png").write_bytes(PNG)
    (bucket / "ab12cd34-link.png").symlink_to(tmp_path / "secret.png")
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    registry = MagicMock()
    registry.get_session.side_effect = lambda sid: SimpleNamespace(working_dir=str(tmp_path)) if sid == "ses_a" else None
    app.state.session_manager = MagicMock()
    app.state.services = SimpleNamespace(registry=registry)
    app.include_router(router)
    return TestClient(app), bucket, tmp_path


def test_serves_the_saved_picture_and_refuses_everything_outside(served):
    client, bucket, root = served
    ok = client.get("/sessions/ses_a/upload-image", params={"path": str(bucket / "ab12cd34-a.png")})
    assert ok.status_code == 200 and ok.content == PNG and ok.headers["content-type"] == "image/png"
    refused = [
        (str(bucket / ".." / "secret.png"), "ses_a"),
        (str(root / "secret.png"), "ses_a"),
        (str(bucket / "ab12cd34-link.png"), "ses_a"),
        (str(bucket / "ab12cd34-n.txt"), "ses_a"),
        (str(bucket / "ab12cd34-x.svg"), "ses_a"),
        ("/etc/passwd", "ses_a"),
        ("ab12cd34-a.png", "ses_a"),
        (str(bucket / "ab12cd34-a.png"), "ses_other"),
    ]
    for path, sid in refused:
        assert client.get(f"/sessions/{sid}/upload-image", params={"path": path}).status_code == 404, path
