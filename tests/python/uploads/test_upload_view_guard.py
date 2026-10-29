from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_uvg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_uvg_logs_"))

from src.api.session_upload_view_routes import resolve_upload_image  # noqa: E402

BUCKETS = pytest.mark.parametrize("bucket_name", [".carnivore_uploads", ".cloude_uploads"])
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


@BUCKETS
def test_a_bucket_that_is_a_symlink_out_serves_nothing(tmp_path: Path, bucket_name: str) -> None:
    project, outside = tmp_path / "p", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "a.png").write_bytes(PNG)
    (project / bucket_name).symlink_to(outside, target_is_directory=True)
    assert resolve_upload_image(str(project), str(project / bucket_name / "a.png")) is None
    assert resolve_upload_image(str(project), str(outside / "a.png")) is None


@BUCKETS
def test_a_real_bucket_still_serves_its_picture(tmp_path: Path, bucket_name: str) -> None:
    (tmp_path / bucket_name).mkdir()
    picture = tmp_path / bucket_name / "a.png"
    picture.write_bytes(PNG)
    assert resolve_upload_image(str(tmp_path), str(picture)) == str(picture.resolve())


@BUCKETS
@pytest.mark.parametrize("sibling", ["{b}_x", "{b}X", "{b}/sub"])
def test_a_sibling_or_nested_folder_serves_nothing(tmp_path: Path, bucket_name: str, sibling: str) -> None:
    (tmp_path / bucket_name).mkdir()
    folder = tmp_path / sibling.format(b=bucket_name)
    folder.mkdir(parents=True)
    (folder / "a.png").write_bytes(PNG)
    assert resolve_upload_image(str(tmp_path), str(folder / "a.png")) is None
