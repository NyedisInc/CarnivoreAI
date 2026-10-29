
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.core import tmux_discovery as td
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import TEST_SOCKET_NAME



def _bundled_tmux() -> Path:
    env = os.environ.get(td.BUNDLED_TMUX_ENV)
    cache = Path(os.environ.get("CARNIVORE_PAYLOAD_CACHE") or Path.home() / ".cache" / "carnivore-payload")
    out = Path(os.environ.get("CARNIVORE_PAYLOAD_OUT") or cache / "out")
    candidates = [Path(env)] if env else []
    candidates += [out / "payload-arm64" / "bin" / "tmux", out / "payload-x86_64" / "bin" / "tmux",
                   Path("/Users/example/worktrees/cloudecode/.payload-cache/x/tmux")]
    return next((c for c in candidates if c.is_file()), candidates[-1])


SPIKE_TMUX = _bundled_tmux()
BREW_TMUX = Path("/opt/homebrew/bin/tmux")
SESSION = "carnivore_skewtest"


def _version(path: Path) -> str:
    return subprocess.run([str(path), "-V"], capture_output=True, text=True).stdout.strip().removeprefix("tmux ")


pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="the payload tmux binaries are macOS builds")


@pytest.fixture(autouse=True)
def _two_real_versions():
    assert SPIKE_TMUX.is_file(), f"static tmux missing ({SPIKE_TMUX}): run macOS/payload/build-payload.sh arm64"
    assert BREW_TMUX.is_file(), f"Homebrew tmux missing ({BREW_TMUX})"
    assert td.tmux_version_key(_version(SPIKE_TMUX)) != td.tmux_version_key(_version(BREW_TMUX)), \
        "bundled and Homebrew tmux are the same major.minor: no skew to test"


@pytest.fixture
def sock(tmp_path, monkeypatch):
    name = TEST_SOCKET_NAME
    assert name != "cloude"
    started_by: list[Path] = []
    td.reset_probe_cache()
    monkeypatch.setattr(td, "WELL_KNOWN_PATHS", ())
    yield name, started_by
    for binary in started_by:
        subprocess.run([str(binary), "-L", name, "kill-server"], capture_output=True)
    td.reset_probe_cache()


def _start_server(binary: Path, name: str, started_by: list) -> None:
    subprocess.run([str(binary), "-L", name, "new-session", "-d", "-s", SESSION, "sleep 300"], check=True)
    started_by.append(binary)
    for _ in range(50):
        if subprocess.run([str(binary), "-L", name, "has-session", "-t", f"={SESSION}"], capture_output=True).returncode == 0:
            return
        time.sleep(0.1)
    raise AssertionError("throwaway server did not come up")


def _path_with(monkeypatch, binary: Path, tmp_path) -> None:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    (d / "tmux").unlink(missing_ok=True)
    (d / "tmux").symlink_to(binary)
    monkeypatch.setenv("PATH", f"{d}:/usr/bin:/bin")


def test_matching_client_lists_fine_and_server_binary_is_preferred(sock, monkeypatch, tmp_path):
    name, started_by = sock
    _start_server(SPIKE_TMUX, name, started_by)
    _path_with(monkeypatch, BREW_TMUX, tmp_path)
    monkeypatch.setenv(td.BUNDLED_TMUX_ENV, str(SPIKE_TMUX))
    td.reset_probe_cache()
    assert td.select_tmux(name) == str(SPIKE_TMUX), "discovery must pick the binary matching the live server"
    listing = TmuxBackend("ses_skew", tmp_path, socket_name=name).discover_existing()
    assert listing.ok and listing.sessions == [SESSION]


def test_skewed_client_gets_the_named_error_and_no_listing(sock, monkeypatch, tmp_path):
    name, started_by = sock
    _start_server(SPIKE_TMUX, name, started_by)
    _path_with(monkeypatch, BREW_TMUX, tmp_path)
    monkeypatch.delenv(td.BUNDLED_TMUX_ENV, raising=False)
    td.reset_probe_cache()
    with pytest.raises(td.TmuxVersionSkewError) as err:
        td.select_tmux(name)
    assert _version(SPIKE_TMUX) in str(err.value) and _version(BREW_TMUX) in str(err.value)
    assert err.value.server_version == _version(SPIKE_TMUX) and err.value.client_version == _version(BREW_TMUX)
    backend = TmuxBackend("ses_skew", tmp_path, socket_name=name)
    listing = backend.discover_existing()
    assert not listing.ok and listing.reason == "version_skew" and listing.sessions == []
    with pytest.raises(td.TmuxVersionSkewError):
        backend._preflight_start()


def test_no_server_uses_the_bundled_binary_when_the_shell_set_it(sock, monkeypatch, tmp_path):
    name, _ = sock
    _path_with(monkeypatch, BREW_TMUX, tmp_path)
    monkeypatch.setenv(td.BUNDLED_TMUX_ENV, str(SPIKE_TMUX))
    td.reset_probe_cache()
    assert os.path.realpath(td.select_tmux(name)) == os.path.realpath(SPIKE_TMUX)
    monkeypatch.delenv(td.BUNDLED_TMUX_ENV)
    td.reset_probe_cache()
    assert td.select_tmux(name) == str(tmp_path / "bin" / "tmux")
    assert TmuxBackend("ses_skew", tmp_path, socket_name=name).discover_existing().ok


def test_bundled_tmux_is_first_candidate_when_the_shell_sets_it(monkeypatch, tmp_path):
    bundled = tmp_path / "tmux"
    bundled.write_text("#!/bin/sh\n")
    bundled.chmod(0o755)
    default = tmp_path / "default-tmux"
    default.write_text("#!/bin/sh\n")
    default.chmod(0o755)
    monkeypatch.setattr(td, "resolve_tmux_path", lambda: str(default))
    monkeypatch.setattr(td, "WELL_KNOWN_PATHS", [])
    monkeypatch.setenv(td.BUNDLED_TMUX_ENV, str(bundled))
    assert td.candidate_tmux_paths() == [str(bundled), str(default)]
    monkeypatch.delenv(td.BUNDLED_TMUX_ENV)
    assert td.candidate_tmux_paths() == [str(default)]
