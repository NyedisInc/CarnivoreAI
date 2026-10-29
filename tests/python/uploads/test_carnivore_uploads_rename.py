from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cu_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cu_logs_"))

from src.api.auth import require_auth  # noqa: E402
from src.api.session_upload_view_routes import router, resolve_upload_image  # noqa: E402
from src.api.uploads import save_upload_to_session_dir  # noqa: E402
from src.core.product_identity import LEGACY_UPLOAD_DIR_NAMES, UPLOAD_DIR_NAME  # noqa: E402
from src.core.upload_sweeper import UploadSweeper  # noqa: E402
from src.core.uploads.bucket_guard import SWEEPABLE_BUCKET_NAMES, SweepOutcome, sweep_verdict, sweep_verdicts  # noqa: E402

NEW, OLD = ".carnivore_uploads", ".cloude_uploads"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _stale(bucket: Path, name: str = "ab12cd34-a.png") -> Path:
    bucket.mkdir(exist_ok=True)
    f = bucket / name
    f.write_bytes(PNG)
    os.utime(f, (time.time() - 86_400, time.time() - 86_400))
    return f


def test_new_upload_lands_in_carnivore_uploads_only(tmp_path):
    target = save_upload_to_session_dir(PNG, "a.png", str(tmp_path))
    assert target.parent == (tmp_path / NEW).resolve()
    assert not (tmp_path / OLD).exists()


def test_old_bucket_file_is_still_served_and_new_one_too(tmp_path):
    old, new = _stale(tmp_path / OLD), _stale(tmp_path / NEW, "ab12cd34-b.png")
    assert resolve_upload_image(str(tmp_path), str(old)) == str(old.resolve())
    assert resolve_upload_image(str(tmp_path), str(new)) == str(new.resolve())


def test_route_serves_a_file_from_the_legacy_bucket(tmp_path):
    old = _stale(tmp_path / OLD)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    registry = MagicMock()
    registry.get_session.return_value = SimpleNamespace(working_dir=str(tmp_path))
    app.state.session_manager = MagicMock()
    app.state.services = SimpleNamespace(registry=registry)
    app.include_router(router)
    r = TestClient(app).get("/sessions/ses_a/upload-image", params={"path": str(old)})
    assert r.status_code == 200 and r.content == PNG


@pytest.mark.asyncio
async def test_sweeper_prunes_both_buckets(tmp_path):
    old, new = _stale(tmp_path / OLD), _stale(tmp_path / NEW)
    result = await UploadSweeper(ttl_seconds=60, interval_seconds=0, project_paths=[str(tmp_path)],
                                 default_dir=tmp_path / "empty").sweep_now()
    assert result["files_pruned"] == 2 and not old.exists() and not new.exists()


def test_verdicts_cover_exactly_the_two_buckets(tmp_path):
    (tmp_path / OLD).mkdir()
    (tmp_path / NEW).mkdir()
    buckets = sorted(v.bucket.name for v in sweep_verdicts(tmp_path) if v.outcome is SweepOutcome.SWEEP)
    assert buckets == [NEW, OLD]
    assert SWEEPABLE_BUCKET_NAMES == (UPLOAD_DIR_NAME, *LEGACY_UPLOAD_DIR_NAMES)


@pytest.mark.parametrize("name", [".cloude_uploads_x", ".carnivore_uploadsX", ".cloude_uploads2", "cloude_uploads",
                                  ".uploads", "..", "../.cloude_uploads"])
def test_guard_refuses_any_other_folder_name(tmp_path, name):
    with pytest.raises(ValueError):
        sweep_verdict(tmp_path, name)


@pytest.mark.parametrize("sibling", [".cloude_uploads_x", ".carnivore_uploadsX"])
@pytest.mark.asyncio
async def test_sibling_folders_are_never_swept(tmp_path, sibling):
    survivor = _stale(tmp_path / sibling)
    await UploadSweeper(ttl_seconds=60, interval_seconds=0, project_paths=[str(tmp_path)],
                        default_dir=tmp_path / "empty").sweep_now()
    assert survivor.exists()


def test_a_traversal_path_is_not_served(tmp_path):
    _stale(tmp_path / NEW)
    (tmp_path / "secret.png").write_bytes(PNG)
    assert resolve_upload_image(str(tmp_path), str(tmp_path / OLD / ".." / "secret.png")) is None
    assert resolve_upload_image(str(tmp_path), str(tmp_path / NEW / ".." / "secret.png")) is None


def test_a_base_that_is_itself_a_bucket_is_refused_for_both_names(tmp_path):
    for name in (OLD, NEW):
        nested = tmp_path / name
        (nested / OLD).mkdir(parents=True, exist_ok=True)
        (nested / NEW).mkdir(exist_ok=True)
        assert all(v.outcome is SweepOutcome.REFUSED for v in sweep_verdicts(nested))
