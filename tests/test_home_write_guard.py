
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_hwg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_hwg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core import claude_hooks
from src.core.test_write_guard import (
    OutsideTempWriteError,
    assert_test_write_allowed,
    running_under_test,
    temp_roots,
)
from tests import settings_write_recorder

REPO_ROOT = Path(__file__).resolve().parents[1]


def _outside_temp_probe(tag: str) -> Path:
    probe = REPO_ROOT / "build" / f"guard-probe-{tag}-{uuid.uuid4().hex}.json"
    assert not probe.exists()
    return probe


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()




def test_guard_is_active_during_this_run() -> None:
    assert running_under_test() is True


def test_guard_allows_a_path_under_the_temp_root(tmp_path: Path) -> None:
    assert_test_write_allowed(tmp_path / "settings.json")


def test_guard_refuses_the_real_claude_settings_path_by_name() -> None:
    real = Path.home() / ".claude" / "settings.json"
    with pytest.raises(OutsideTempWriteError) as excinfo:
        assert_test_write_allowed(real)
    assert str(real.resolve()) in str(excinfo.value)


def test_guard_refuses_any_path_outside_temp_even_inside_the_repo() -> None:
    with pytest.raises(OutsideTempWriteError):
        assert_test_write_allowed(REPO_ROOT / "not-a-real-file.json")


def test_guard_refuses_when_the_temp_root_cannot_be_resolved(monkeypatch) -> None:

    def _boom() -> str:
        raise OSError("no temp dir")

    monkeypatch.setattr(tempfile, "gettempdir", _boom)
    monkeypatch.delenv("TMPDIR", raising=False)
    with pytest.raises(OutsideTempWriteError) as excinfo:
        assert_test_write_allowed(Path("/anything/at/all.json"))
    assert "could not" in str(excinfo.value).lower()




def test_strip_managed_hooks_has_no_implicit_default() -> None:
    with pytest.raises(TypeError):
        claude_hooks.strip_managed_hooks()  # type: ignore[call-arg]


def test_direct_import_cannot_write_outside_temp() -> None:
    outside_temp = _outside_temp_probe("direct")

    with pytest.raises(OutsideTempWriteError) as excinfo:
        claude_hooks.strip_managed_hooks(outside_temp)
    assert str(outside_temp.resolve()) in str(excinfo.value)
    assert not outside_temp.exists()


def test_default_settings_path_is_redirected_during_tests(tmp_path: Path) -> None:
    resolved = claude_hooks.default_settings_path()
    assert_test_write_allowed(resolved)
    assert resolved != Path.home() / ".claude" / "settings.json"




def test_app_startup_path_writes_only_into_temp() -> None:
    real = Path.home() / ".claude" / "settings.json"
    before = _sha256(real)

    target = claude_hooks.default_settings_path()

    assert target != real, "the production default is not redirected"
    assert any(
        target.resolve().is_relative_to(root) for root in temp_roots()
    ), f"{target} is outside every temp root; this test refuses to write it"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "curl ... ; : "
                                        + claude_hooks.CLOUDECODE_HOOKS_MARKER
                                    ),
                                }
                            ],
                        }
                    ]
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert claude_hooks.strip_managed_hooks(target) is True

    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert "hooks" not in written
    assert _sha256(real) == before


def test_guard_survives_a_subprocess_fork() -> None:
    outside_temp = _outside_temp_probe("subprocess")

    program = (
        "import sys, pathlib\n"
        "sys.path.insert(0, %r)\n"
        "from src.core import claude_hooks\n"
        "from src.core.test_write_guard import OutsideTempWriteError\n"
        "target = pathlib.Path(%r)\n"
        "try:\n"
        "    claude_hooks.strip_managed_hooks(target)\n"
        "except OutsideTempWriteError as exc:\n"
        "    print('REFUSED:' + str(exc))\n"
        "    raise SystemExit(0)\n"
        "print('WROTE')\n"
        "raise SystemExit(1)\n"
    ) % (str(REPO_ROOT), str(outside_temp))

    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "REFUSED:" in proc.stdout
    assert str(outside_temp.resolve()) in proc.stdout
    assert not outside_temp.exists()




def test_settings_canary_still_fails_on_a_write_this_process_made(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "settings.json"
    before = ("absent", "")
    settings_write_recorder.install(watched)
    try:
        src = tmp_path / "settings.json.cloudecode-tmp"
        src.write_text('{"hooks": {}}\n', encoding="utf-8")
        os.replace(src, watched)
        assert settings_write_recorder.write_was_recorded(watched) is True

        after = (
            "present",
            hashlib.sha256(watched.read_bytes()).hexdigest(),
        )
        verdict, message = settings_write_recorder.canary_verdict(
            before, after, settings_write_recorder.write_was_recorded(watched)
        )
        assert verdict == "fail"
        assert "THE TEST SUITE MODIFIED" in message
    finally:
        settings_write_recorder.remove(watched)


def test_settings_canary_still_fails_on_a_deletion_this_process_made(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "settings.json"
    watched.write_text("{}\n", encoding="utf-8")
    before = ("present", hashlib.sha256(watched.read_bytes()).hexdigest())
    settings_write_recorder.install(watched)
    try:
        watched.unlink()
        assert settings_write_recorder.write_was_recorded(watched) is True

        after = ("absent", "")
        verdict, message = settings_write_recorder.canary_verdict(
            before, after, settings_write_recorder.write_was_recorded(watched)
        )
        assert verdict == "fail"
        assert "THE TEST SUITE MODIFIED" in message
    finally:
        settings_write_recorder.remove(watched)


def test_settings_canary_ignores_a_write_to_a_different_file(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "settings.json"
    elsewhere = tmp_path / "unrelated.json"
    settings_write_recorder.install(watched)
    try:
        elsewhere.write_text("{}\n", encoding="utf-8")
        assert settings_write_recorder.write_was_recorded(watched) is False
    finally:
        settings_write_recorder.remove(watched)


def test_settings_canary_does_not_record_a_write_that_failed(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "settings.json"
    settings_write_recorder.install(watched)
    try:
        with pytest.raises(FileNotFoundError):
            os.replace(tmp_path / "missing.cloudecode-tmp", watched)
        assert settings_write_recorder.write_was_recorded(watched) is False
    finally:
        settings_write_recorder.remove(watched)


def test_settings_canary_recorder_supports_two_watched_paths_at_once(
    tmp_path: Path,
) -> None:
    watched_a = tmp_path / "a" / "settings.json"
    watched_b = tmp_path / "b" / "settings.json"
    watched_a.parent.mkdir()
    watched_b.parent.mkdir()
    settings_write_recorder.install(watched_a)
    settings_write_recorder.install(watched_b)
    try:
        watched_a.write_text("{}\n", encoding="utf-8")
        assert settings_write_recorder.write_was_recorded(watched_a) is True
        assert settings_write_recorder.write_was_recorded(watched_b) is False
    finally:
        settings_write_recorder.remove(watched_a)
        settings_write_recorder.remove(watched_b)


def test_settings_canary_does_not_fail_on_an_untracked_external_change() -> None:
    verdict, message = settings_write_recorder.canary_verdict(
        ("present", "aaa"), ("present", "bbb"), False
    )
    assert verdict == "warn"
    assert "unrelated process" in message


def test_settings_canary_verdict_is_ok_when_nothing_changed() -> None:
    assert settings_write_recorder.canary_verdict(
        ("absent", ""), ("absent", ""), False
    ) == ("ok", "")


def test_settings_canary_verdict_still_fails_on_an_unreadable_fingerprint() -> None:
    verdict, _ = settings_write_recorder.canary_verdict(
        ("unreadable", "boom"), ("absent", ""), False
    )
    assert verdict == "fail"
