from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "upgrade_lib" / "version_probe.py"
if str(ROOT / "scripts" / "upgrade_lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "upgrade_lib"))

# ruff: noqa: E402
import version_probe  # type: ignore


@pytest.fixture(autouse=True)
def _restore_src_modules_and_path():
    saved_path = list(sys.path)
    saved_modules = {n: m for n, m in sys.modules.items() if n == "src" or n.startswith("src.")}
    yield
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]
    sys.modules.update(saved_modules)
    sys.path[:] = saved_path




def test_current_version_resolves_from_real_repo():
    version = version_probe.current_version(ROOT)
    assert isinstance(version, str)


def test_current_version_empty_when_unresolvable(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDE_APP_VERSION", raising=False)
    (tmp_path / "src" / "core").mkdir(parents=True)
    version = version_probe.current_version(tmp_path)
    assert version == ""


def test_env_override_outranks_an_unresolvable_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDE_APP_VERSION", "9.9.9")
    (tmp_path / "src" / "core").mkdir(parents=True)
    assert version_probe.current_version(tmp_path) == "9.9.9"




def test_resolve_remote_prefers_configured_over_origin(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"updates": {"remote": "https://example.com/configured.git"}}))
    remote = version_probe.resolve_remote(tmp_path, config_path)
    assert remote == "https://example.com/configured.git"


def test_resolve_remote_falls_back_to_fallback_remote(tmp_path):
    remote = version_probe.resolve_remote(tmp_path, None)
    version_probe._install_src_on_path(tmp_path)
    from src.core.update_check import FALLBACK_REMOTE

    assert remote == FALLBACK_REMOTE




def test_install_src_on_path_does_not_leak_between_dirs(tmp_path):
    other = tmp_path / "other_install"
    other.mkdir()
    version_probe._install_src_on_path(ROOT)
    assert sys.path[0] == str(ROOT.resolve())
    version_probe._install_src_on_path(other)
    assert sys.path[0] == str(other.resolve())
    assert sys.path[0] != str(ROOT.resolve())




def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROBE), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_current_exit_0_on_real_repo():
    result = _run("current", "--install-dir", str(ROOT))
    assert result.returncode in (0, 3)
    if result.returncode == 0:
        assert result.stdout.strip()
    else:
        assert result.stdout.strip() == ""
        assert "could not determine" in result.stderr


def test_cli_tags_could_not_evaluate_on_bad_remote():
    result = _run(
        "tags",
        "--install-dir",
        str(ROOT),
        "--remote",
        "https://this-host-does-not-exist.invalid/nowhere.git",
    )
    assert result.returncode == 3
    assert "could not list release tags" in result.stderr


def test_cli_latest_could_not_evaluate_on_bad_remote():
    result = _run(
        "latest",
        "--install-dir",
        str(ROOT),
        "--remote",
        "https://this-host-does-not-exist.invalid/nowhere.git",
    )
    assert result.returncode == 3


def test_cli_check_tag_fail_when_tag_absent_from_list(monkeypatch):
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        bare = Path(d) / "bare.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        result = _run(
            "check-tag",
            "--install-dir",
            str(ROOT),
            "--remote",
            str(bare),
            "9.9.9",
        )
        assert result.returncode == 2
        assert "is not a published release tag" in result.stderr


def test_cli_check_tag_pass_when_tag_present():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        bare = Path(d) / "bare.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
        subprocess.run(["git", "-C", str(repo), "tag", "1.2.3"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
        subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:refs/heads/main", "1.2.3"], check=True)

        result = _run(
            "check-tag",
            "--install-dir",
            str(ROOT),
            "--remote",
            str(bare),
            "1.2.3",
        )
        assert result.returncode == 0, result.stderr

        latest = _run("latest", "--install-dir", str(ROOT), "--remote", str(bare))
        assert latest.returncode == 0
        assert latest.stdout.strip() == "1.2.3"


def test_tag_commands_only_map_remote_failures_to_exit_3(monkeypatch, capsys):
    import argparse

    args = argparse.Namespace(install_dir=str(ROOT), remote="x", tag="1.0.0")
    for cmd in (version_probe._cmd_tags, version_probe._cmd_latest, version_probe._cmd_check_tag):
        monkeypatch.setattr(
            version_probe, "list_release_tags",
            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("programming error")),
        )
        with pytest.raises(ValueError):
            cmd(args)
        monkeypatch.setattr(
            version_probe, "list_release_tags",
            lambda *_a, **_k: (_ for _ in ()).throw(version_probe.TagListError("down")),
        )
        assert cmd(args) == 3
    assert "could not list release tags" in capsys.readouterr().err
