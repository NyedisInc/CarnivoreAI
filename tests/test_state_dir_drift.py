from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_drift_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_drift_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import Settings

BASH_LIB = ROOT / "scripts" / "upgrade_lib" / "upgrade_rollback_common.sh"


def _resolve_state_dir_bash(install_dir: Path, env: dict) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; resolve_state_dir "$2"',
            "_",
            str(BASH_LIB),
            str(install_dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"resolve_state_dir subprocess failed (rc={result.returncode}): "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return result.stdout.rstrip("\n")


def _minimal_child_env(home: Path, path: str) -> dict:
    return {"HOME": str(home), "PATH": path}


def test_drift_state_dir_via_process_env(tmp_path, monkeypatch):
    target = tmp_path / "via-process-env"
    install_dir = tmp_path / "install_a"
    install_dir.mkdir()

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(target))
    python_settings = Settings(
        _env_file=None,
        DEFAULT_WORKING_DIR=str(tmp_path / "wd"),
        LOG_DIRECTORY=None,
        TOTP_SECRET="x",
        JWT_SECRET="y",
    )
    python_result = str(python_settings.get_state_dir())

    env = _minimal_child_env(tmp_path, os.environ.get("PATH", "/usr/bin:/bin"))
    env["CLOUDE_STATE_DIR"] = str(target)
    bash_result = _resolve_state_dir_bash(install_dir, env)

    assert python_result == bash_result == str(target)


def test_drift_state_dir_via_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)
    target = tmp_path / "via-dotenv"
    install_dir = tmp_path / "install_b"
    install_dir.mkdir()
    (install_dir / ".env").write_text(f"CLOUDE_STATE_DIR={target}\nPORT=8000\n")

    python_settings = Settings(
        _env_file=install_dir / ".env",
        DEFAULT_WORKING_DIR=str(tmp_path / "wd2"),
        LOG_DIRECTORY=None,
        TOTP_SECRET="x",
        JWT_SECRET="y",
    )
    python_result = str(python_settings.get_state_dir())

    env = _minimal_child_env(tmp_path, os.environ.get("PATH", "/usr/bin:/bin"))
    bash_result = _resolve_state_dir_bash(install_dir, env)

    assert python_result == bash_result == str(target)


def test_drift_state_dir_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)
    install_dir = tmp_path / "install_c"
    install_dir.mkdir()

    python_settings = Settings(
        _env_file=None,
        DEFAULT_WORKING_DIR=str(tmp_path / "wd3"),
        LOG_DIRECTORY=None,
        TOTP_SECRET="x",
        JWT_SECRET="y",
    )
    import unittest.mock as _mock

    with _mock.patch.object(Path, "home", return_value=tmp_path):
        python_result = str(python_settings.get_state_dir())

    env = _minimal_child_env(tmp_path, os.environ.get("PATH", "/usr/bin:/bin"))
    bash_result = _resolve_state_dir_bash(install_dir, env)

    expected = str(tmp_path / "Library" / "Application Support" / "Carnivore")
    assert python_result == bash_result == expected


def test_drift_state_dir_falls_back_to_legacy_name_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)
    install_dir = tmp_path / "install_legacyfallback"
    install_dir.mkdir()

    python_settings = Settings(
        _env_file=None,
        DEFAULT_WORKING_DIR=str(tmp_path / "wd4"),
        LOG_DIRECTORY=None,
        TOTP_SECRET="x",
        JWT_SECRET="y",
    )
    import unittest.mock as _mock

    with _mock.patch.object(Path, "home", return_value=tmp_path):
        legacy = tmp_path / "Library" / "Application Support" / "CloudeCode"
        legacy.mkdir(parents=True)
        python_result = str(python_settings.get_state_dir())

    env = _minimal_child_env(tmp_path, os.environ.get("PATH", "/usr/bin:/bin"))
    bash_result = _resolve_state_dir_bash(install_dir, env)

    expected = str(tmp_path / "Library" / "Application Support" / "Carnivore")
    assert python_result == bash_result == expected
    assert not legacy.exists()


def test_drift_disagreement_would_be_caught(tmp_path):
    target = tmp_path / "meta-check"
    wrong = str(target) + "/"

    with pytest.raises(AssertionError):
        assert str(target) == wrong



STATE_FILE_CASES = [
    "refresh_tokens.db",
    "session_metadata.json",
    "pinned_themes.json",
    "unread_state.json",
]


def _resolve_state_file_bash(install_dir: Path, filename: str, env: dict) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; resolve_state_file "$2" "$3"',
            "_",
            str(BASH_LIB),
            str(install_dir),
            filename,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"resolve_state_file subprocess failed (rc={result.returncode}): "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return result.stdout.rstrip("\n")


def _file_case_setup(tmp_path, monkeypatch, name, declare_state_dir=True):
    install_dir = tmp_path / f"install_{name}"
    install_dir.mkdir()
    old_dir = tmp_path / f"old_{name}"
    old_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLOUDE_STATE_DIR", raising=False)
    kwargs = {}
    if declare_state_dir:
        new_dir = tmp_path / f"new_{name}"
        new_dir.mkdir()
        (install_dir / ".env").write_text(
            f"CLOUDE_STATE_DIR={new_dir}\nLOG_DIRECTORY={old_dir}\n"
        )
        kwargs["CLOUDE_STATE_DIR"] = str(new_dir)
    else:
        new_dir = tmp_path / "Library" / "Application Support" / "Carnivore"
        new_dir.mkdir(parents=True, exist_ok=True)
        (install_dir / ".env").write_text(f"LOG_DIRECTORY={old_dir}\n")
    settings_obj = Settings(
        _env_file=None,
        DEFAULT_WORKING_DIR=str(tmp_path / "wd"),
        LOG_DIRECTORY=str(old_dir),
        TOTP_SECRET="testsecretnotreal",
        JWT_SECRET="testjwtnotreal",
        **kwargs,
    )
    env = _minimal_child_env(tmp_path, os.environ.get("PATH", "/usr/bin:/bin"))
    return settings_obj, install_dir, new_dir, old_dir, env


@pytest.mark.parametrize("filename", STATE_FILE_CASES)
def test_drift_state_file_present_in_neither(tmp_path, monkeypatch, filename):
    s, install_dir, new_dir, _old, env = _file_case_setup(
        tmp_path, monkeypatch, "neither" + filename.replace(".", "")
    )
    py = str(s._resolve_state_file(filename))
    sh = _resolve_state_file_bash(install_dir, filename, env)
    assert py == sh == str(new_dir / filename)


@pytest.mark.parametrize("filename", STATE_FILE_CASES)
def test_drift_state_file_only_new(tmp_path, monkeypatch, filename):
    s, install_dir, new_dir, _old, env = _file_case_setup(
        tmp_path, monkeypatch, "new" + filename.replace(".", "")
    )
    (new_dir / filename).write_text("x")
    py = str(s._resolve_state_file(filename))
    sh = _resolve_state_file_bash(install_dir, filename, env)
    assert py == sh == str(new_dir / filename)


@pytest.mark.parametrize("filename", STATE_FILE_CASES)
def test_drift_state_file_only_old(tmp_path, monkeypatch, filename):
    s, install_dir, new_dir, old_dir, env = _file_case_setup(
        tmp_path, monkeypatch, "old" + filename.replace(".", ""),
        declare_state_dir=False,
    )
    (old_dir / filename).write_text("x")
    py = str(s._resolve_state_file(filename))
    sh = _resolve_state_file_bash(install_dir, filename, env)
    assert py == sh == str(old_dir / filename)
    assert sh != str(new_dir / filename), (
        "the fallback did nothing - this case is indistinguishable from "
        "the directory-only resolver, so it proves nothing"
    )


@pytest.mark.parametrize("filename", STATE_FILE_CASES)
def test_drift_state_file_in_both(tmp_path, monkeypatch, filename):
    s, install_dir, new_dir, old_dir, env = _file_case_setup(
        tmp_path, monkeypatch, "both" + filename.replace(".", ""),
        declare_state_dir=False,
    )
    (new_dir / filename).write_text("new")
    (old_dir / filename).write_text("old")
    py = str(s._resolve_state_file(filename))
    sh = _resolve_state_file_bash(install_dir, filename, env)
    assert py == sh == str(new_dir / filename)
    assert (old_dir / filename).read_text() == "old", (
        "resolving must never delete or rewrite the old copy"
    )


def test_refresh_tokens_path_uses_the_fallback(tmp_path, monkeypatch):
    s, _install, new_dir, old_dir, _env = _file_case_setup(
        tmp_path, monkeypatch, "refreshfallback", declare_state_dir=False
    )
    (old_dir / "refresh_tokens.db").write_text("existing tokens")
    assert str(s.get_refresh_tokens_path()) == str(old_dir / "refresh_tokens.db")
    assert str(s.get_refresh_tokens_path()) != str(new_dir / "refresh_tokens.db")


@pytest.mark.parametrize("filename", STATE_FILE_CASES)
def test_an_explicit_state_dir_diverges_and_the_backup_still_finds_the_legacy_file(
    tmp_path, monkeypatch, filename
):
    s, install_dir, new_dir, old_dir, env = _file_case_setup(
        tmp_path, monkeypatch, "explicitdiverge" + filename.replace(".", "")
    )
    (old_dir / filename).write_text("real user data")

    assert s.state_dir_is_explicit()
    assert str(s._resolve_state_file(filename)) == str(new_dir / filename)
    assert _resolve_state_file_bash(install_dir, filename, env) == str(
        old_dir / filename
    )
    assert (old_dir / filename).read_text() == "real user data"
