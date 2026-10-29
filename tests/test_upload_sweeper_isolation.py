from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_swi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_swi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import test_write_guard  # noqa: E402
from src.core.upload_sweeper import UploadSweeper, datastore_project_paths  # noqa: E402
from src.core.uploads import bucket_guard  # noqa: E402
from src.core.uploads.bucket_guard import SweepOutcome  # noqa: E402


BUCKET_NAMES = (".carnivore_uploads", ".cloude_uploads")
UPLOAD_DIR_NAME = BUCKET_NAMES[0]


@pytest.fixture(autouse=True, params=BUCKET_NAMES)
def _bucket_name(request, monkeypatch):
    monkeypatch.setitem(globals(), "UPLOAD_DIR_NAME", request.param)
    return request.param


def sweep_verdict(base):
    return bucket_guard.sweep_verdict(base, UPLOAD_DIR_NAME)


def _seed_old_file(base: Path, name: str = "stale.png") -> Path:
    bucket = base / UPLOAD_DIR_NAME
    bucket.mkdir(parents=True, exist_ok=True)
    target = bucket / name
    target.write_bytes(b"payload-that-must-survive")
    old = time.time() - 86_400
    os.utime(target, (old, old))
    assert target.exists()
    return target


def _sweeper(bases, default_dir: Path, ttl_seconds: int = 60) -> UploadSweeper:
    return UploadSweeper(
        ttl_seconds=ttl_seconds,
        interval_seconds=0,
        project_paths=bases,
        default_dir=default_dir,
    )




@pytest.mark.asyncio
async def test_sweep_outside_every_temp_root_refuses_and_deletes_nothing(
    tmp_path, monkeypatch
):
    allowed_root = tmp_path / "the-only-temp-root"
    allowed_root.mkdir()
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [allowed_root])

    project = tmp_path / "pretend-real-project"
    project.mkdir()
    survivor = _seed_old_file(project)

    empty_default = tmp_path / "default-dir"
    empty_default.mkdir()

    result = await _sweeper([str(project)], empty_default).sweep_now()

    assert survivor.exists(), (
        "The sweeper deleted a file under a base outside every temp root. "
        "That is the defect this test exists to catch."
    )
    assert survivor.read_bytes() == b"payload-that-must-survive"
    assert (project / UPLOAD_DIR_NAME).is_dir()
    assert result["files_pruned"] == 0
    assert result["bases_refused"] >= 1


@pytest.mark.asyncio
async def test_guard_does_not_neuter_a_legitimate_sweep(tmp_path, monkeypatch):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])

    project = tmp_path / "legit"
    project.mkdir()
    doomed = _seed_old_file(project)

    empty_default = tmp_path / "default-dir"
    empty_default.mkdir()

    result = await _sweeper([str(project)], empty_default).sweep_now()

    assert not doomed.exists()
    assert result["files_pruned"] == 1
    assert result["bases_refused"] == 0




@pytest.mark.parametrize(
    "real_path",
    [
        str(Path.home()),
        str(Path.home() / "Development"),
        str(ROOT),
    ],
)
def test_real_non_disposable_paths_are_refused_by_query_only(real_path):
    verdict = sweep_verdict(real_path)
    assert verdict.outcome is SweepOutcome.REFUSED, (
        f"{real_path} was not refused during a test run: {verdict.reason}"
    )
    assert verdict.bucket is None




@pytest.mark.asyncio
async def test_undetermined_project_list_sweeps_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])

    default_dir = tmp_path / "default-dir"
    default_dir.mkdir()
    survivor = _seed_old_file(default_dir)

    result = await _sweeper(None, default_dir).sweep_now()

    assert survivor.exists(), (
        "The sweeper pruned the default dir despite not knowing which "
        "projects were configured."
    )
    assert result["files_pruned"] == 0
    assert result["project_list_determined"] is False




@pytest.mark.asyncio
async def test_symlinked_bucket_is_refused_and_its_target_survives(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])

    elsewhere = tmp_path / "somebody-elses-data"
    elsewhere.mkdir()
    survivor = elsewhere / "important.txt"
    survivor.write_bytes(b"not an upload")
    old = time.time() - 86_400
    os.utime(survivor, (old, old))

    project = tmp_path / "project"
    project.mkdir()
    (project / UPLOAD_DIR_NAME).symlink_to(elsewhere, target_is_directory=True)

    result = await _sweeper([str(project)], tmp_path / "nope").sweep_now()

    assert survivor.exists(), "A symlinked bucket was followed and its target pruned."
    assert result["files_pruned"] == 0
    assert result["bases_refused"] >= 1


@pytest.mark.parametrize("bad_base", ["", "   ", None])
def test_empty_or_missing_base_is_refused(bad_base):
    verdict = sweep_verdict(bad_base)
    assert verdict.outcome is SweepOutcome.REFUSED
    assert verdict.bucket is None


def test_filesystem_root_as_base_is_refused():
    verdict = sweep_verdict("/")
    assert verdict.outcome is SweepOutcome.REFUSED


@pytest.mark.asyncio
async def test_bucket_that_is_a_regular_file_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])

    project = tmp_path / "project"
    project.mkdir()
    impostor = project / UPLOAD_DIR_NAME
    impostor.write_bytes(b"i am a file, not a bucket")
    old = time.time() - 86_400
    os.utime(impostor, (old, old))

    await _sweeper([str(project)], tmp_path / "nope").sweep_now()

    assert impostor.is_file()
    assert impostor.read_bytes() == b"i am a file, not a bucket"


@pytest.mark.asyncio
async def test_nested_directory_inside_bucket_is_not_recursed_into(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])

    project = tmp_path / "project"
    project.mkdir()
    _seed_old_file(project)
    nested = project / UPLOAD_DIR_NAME / "subdir"
    nested.mkdir()
    deep = nested / "deep.txt"
    deep.write_bytes(b"deep")
    old = time.time() - 86_400
    os.utime(deep, (old, old))

    await _sweeper([str(project)], tmp_path / "nope").sweep_now()

    assert deep.exists(), "The pruner recursed below the bucket."




def test_guard_is_inert_when_not_under_test(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv(test_write_guard.TEST_MODE_ENV_VAR, raising=False)
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path / "nowhere"])

    project = tmp_path / "prod-project"
    (project / UPLOAD_DIR_NAME).mkdir(parents=True)

    verdict = sweep_verdict(str(project))
    assert verdict.outcome is SweepOutcome.SWEEP
    assert verdict.bucket == (project / UPLOAD_DIR_NAME).resolve()




class _FakeView:

    def __init__(self, projects, writable=True):
        self.projects = projects
        self.writable = writable


def test_datastore_project_paths_reads_a_good_list():
    view = _FakeView([{"path": "/a"}, {"path": "/b"}])
    assert datastore_project_paths(view) == ["/a", "/b"]


def test_datastore_project_paths_distinguishes_empty_from_unknown():
    assert datastore_project_paths(_FakeView([])) == []
    assert datastore_project_paths(_FakeView(None)) is None


def test_datastore_project_paths_refuses_an_unreadable_datastore():
    assert datastore_project_paths(_FakeView([], writable=False)) is None
    assert (
        datastore_project_paths(_FakeView([{"path": "/a"}], writable=False)) is None
    )


@pytest.mark.parametrize(
    "projects",
    [
        [{"path": "/a"}, {"path": ""}],
        [{"path": "/a"}, {"path": None}],
        [{"path": "/a"}, {}],
        [{"path": "/a"}, object()],
    ],
)
def test_datastore_project_paths_refuses_a_partial_list(projects):
    assert datastore_project_paths(_FakeView(projects)) is None




async def _destroy_with_uploads_dir(tmp_path, working_dir: Path):
    from unittest.mock import MagicMock

    import src.core.session_manager as sm_mod
    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    object.__setattr__(
        sm_mod.settings,
        "get_session_metadata_path",
        lambda: tmp_path / "session_metadata.json",
    )

    manager = SessionManager()
    backend = MagicMock()

    async def _stop():
        return None

    backend.stop = _stop
    backend.is_alive = MagicMock(return_value=True)
    backend.tmux_session = "cloude_iso01"
    manager._registry.register(
        Session(
            id="ses_iso01",
            working_dir=str(working_dir),
            status=SessionStatus.RUNNING,
        ),
        backend,
    )
    await manager.destroy_session()


@pytest.mark.asyncio
async def test_destroy_session_rmtree_refuses_outside_every_temp_root(
    tmp_path, monkeypatch
):
    allowed_root = tmp_path / "the-only-temp-root"
    allowed_root.mkdir()
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [allowed_root])

    working_dir = tmp_path / "pretend-real-project"
    working_dir.mkdir()
    survivor = _seed_old_file(working_dir, "keep.png")

    await _destroy_with_uploads_dir(tmp_path, working_dir)

    assert survivor.exists(), (
        "destroy_session rmtree'd an uploads dir outside every temp root."
    )


@pytest.mark.asyncio
async def test_destroy_session_still_cleans_a_permitted_uploads_dir(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])

    working_dir = tmp_path / "legit"
    working_dir.mkdir()
    doomed = _seed_old_file(working_dir, "gone.png")

    await _destroy_with_uploads_dir(tmp_path, working_dir)

    assert not doomed.exists()
    assert not (working_dir / UPLOAD_DIR_NAME).exists()


def test_base_that_is_itself_an_uploads_dir_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(test_write_guard, "temp_roots", lambda: [tmp_path])
    nested = tmp_path / UPLOAD_DIR_NAME
    (nested / UPLOAD_DIR_NAME).mkdir(parents=True)
    verdict = sweep_verdict(str(nested))
    assert verdict.outcome is SweepOutcome.REFUSED


@pytest.mark.asyncio
async def test_run_starts_when_the_project_list_is_undetermined(tmp_path):
    sweeper = UploadSweeper(
        ttl_seconds=1,
        interval_seconds=3600,
        project_paths=None,
        default_dir=str(tmp_path),
    )
    task = asyncio.create_task(sweeper.run())
    await asyncio.sleep(0)
    assert not task.done(), "run() died before its first sleep"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
