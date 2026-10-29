
from __future__ import annotations

import errno
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_presence_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_presence_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db_models import (
    PROJECT_PRESENCE_MISSING,
    PROJECT_PRESENCE_PRESENT,
    PROJECT_PRESENCE_UNREACHABLE,
)
from src.core.project_presence import check_presence


def _raiser(exc: BaseException):

    def _stat_fn(_path: str):
        raise exc

    return _stat_fn


def _oserror(code: int, message: str) -> OSError:
    return OSError(code, message)




def test_enoent_is_missing():
    result = check_presence(
        "/does/not/exist", stat_fn=_raiser(_oserror(errno.ENOENT, "No such file or directory"))
    )
    assert result.presence == PROJECT_PRESENCE_MISSING
    assert "ENOENT" in result.detail


def test_eacces_is_unreachable_not_missing():
    result = check_presence(
        "/root/secret", stat_fn=_raiser(_oserror(errno.EACCES, "Permission denied"))
    )
    assert result.presence == PROJECT_PRESENCE_UNREACHABLE
    assert "EACCES" in result.detail


def test_eperm_is_unreachable():
    result = check_presence(
        "/blocked", stat_fn=_raiser(_oserror(errno.EPERM, "Operation not permitted"))
    )
    assert result.presence == PROJECT_PRESENCE_UNREACHABLE
    assert "EPERM" in result.detail


def test_eloop_is_unreachable():
    result = check_presence(
        "/looping", stat_fn=_raiser(_oserror(errno.ELOOP, "Too many levels of symbolic links"))
    )
    assert result.presence == PROJECT_PRESENCE_UNREACHABLE
    assert "ELOOP" in result.detail


def test_enotdir_is_unreachable():
    result = check_presence(
        "/some/file/child", stat_fn=_raiser(_oserror(errno.ENOTDIR, "Not a directory"))
    )
    assert result.presence == PROJECT_PRESENCE_UNREACHABLE
    assert "ENOTDIR" in result.detail


def test_stat_timeout_is_unreachable():
    result = check_presence("/mnt/asleep", stat_fn=_raiser(TimeoutError("no response")))
    assert result.presence == PROJECT_PRESENCE_UNREACHABLE
    assert "TIMEOUT" in result.detail


def test_no_two_of_the_five_collapse_into_each_other():
    cases = {
        "ENOENT": _raiser(_oserror(errno.ENOENT, "gone")),
        "EACCES": _raiser(_oserror(errno.EACCES, "denied")),
        "ELOOP": _raiser(_oserror(errno.ELOOP, "loop")),
        "ENOTDIR": _raiser(_oserror(errno.ENOTDIR, "not a dir")),
        "TIMEOUT": _raiser(TimeoutError("hung")),
    }
    results = {name: check_presence("/x", stat_fn=fn) for name, fn in cases.items()}

    assert results["ENOENT"].presence == PROJECT_PRESENCE_MISSING
    for name in ("EACCES", "ELOOP", "ENOTDIR", "TIMEOUT"):
        assert results[name].presence == PROJECT_PRESENCE_UNREACHABLE

    details = {name: r.detail for name, r in results.items()}
    assert len(set(details.values())) == 5, details


def test_unclassified_exception_from_the_probe_is_unreachable_not_present():
    result = check_presence("/x", stat_fn=_raiser(ValueError("unexpected")))
    assert result.presence == PROJECT_PRESENCE_UNREACHABLE
    assert result.presence != PROJECT_PRESENCE_PRESENT
    assert "ValueError" in result.detail


def test_present_directory():
    with tempfile.TemporaryDirectory() as d:
        result = check_presence(d)
        assert result.presence == PROJECT_PRESENCE_PRESENT
        assert result.detail is None


def test_root_that_is_a_file_not_a_directory_is_unreachable():
    with tempfile.NamedTemporaryFile() as f:
        result = check_presence(f.name)
        assert result.presence == PROJECT_PRESENCE_UNREACHABLE
        assert "ENOTDIR" in result.detail




@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root bypasses directory permission bits; the EACCES this test "
    "depends on never fires when tests run as root",
)
def test_chmod_000_reports_unreachable_not_missing():
    with tempfile.TemporaryDirectory() as parent:
        blocked_dir = Path(parent) / "blocked"
        blocked_dir.mkdir()
        child = blocked_dir / "project"
        child.mkdir()
        os.chmod(blocked_dir, 0o000)
        try:
            result = check_presence(str(child))
        finally:
            os.chmod(blocked_dir, 0o755)

        assert result.presence == PROJECT_PRESENCE_UNREACHABLE, (
            "a project behind a permission wall must never be reported as "
            f"'missing' - got presence={result.presence!r} detail="
            f"{result.detail!r}"
        )
        assert result.presence != PROJECT_PRESENCE_MISSING


def test_unchecked_is_never_produced_by_check_presence():
    with tempfile.TemporaryDirectory() as d:
        assert check_presence(d).presence != "unchecked"
    assert (
        check_presence("/nope", stat_fn=_raiser(_oserror(errno.ENOENT, "x"))).presence
        != "unchecked"
    )
