
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest

from src.core.sessions.pane_listing_cache import invalidate_pane_listing
from src.core.sessions.tmux_listing_fold import split_folded_rows
from src.core.tmux_transport.pane_listing import parse_pane_listing
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

VICTIM = "zvictim"
ATTACKER = "attacker"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


def _forged_folder(tmp_path: Path, epoch: str) -> Path:
    fake_row = f"P|{VICTIM}|1|zsh|999|{epoch}|%99|0|80|24|1|1|x"
    folder = tmp_path / f"a\n{fake_row}"
    folder.mkdir()
    return folder


@pytest.fixture
def forged_server(tmp_path: Path, tmux_test_socket: str) -> Iterator[Path]:
    try:
        assert _tmux("new-session", "-d", "-s", VICTIM, "-c", str(tmp_path), "sleep 600").returncode == 0
        epoch = _tmux("display-message", "-p", "-t", f"={VICTIM}:", "#{session_created}").stdout.strip()
        folder = _forged_folder(tmp_path, epoch)
        done = _tmux("new-session", "-d", "-s", ATTACKER, "-c", str(folder), "sleep 600")
        assert done.returncode == 0, done.stderr
        yield folder
    finally:
        _tmux("kill-server")


def _backend(tmp_path: Path) -> TmuxBackend:
    return TmuxBackend(session_id="__probe__", working_dir=tmp_path, on_output=None,
                       socket_name=TEST_SOCKET_NAME)


def _assert_no_forgery(rows: list, folder: Path) -> None:
    by_name = {row["name"]: row for row in rows}
    assert sorted(by_name) == [ATTACKER, VICTIM] and len(rows) == 2
    assert by_name[VICTIM]["pane_dead"] == "0", "a forged row must not mark a live session dead"
    assert by_name[VICTIM]["pid"] != 999
    assert by_name[ATTACKER]["pane_current_path"] == str(folder.resolve())


@requires_tmux
def test_lone_pane_listing_ignores_a_forged_row(forged_server: Path, tmp_path: Path) -> None:
    listing = _backend(tmp_path)._probe_pane_status_all()
    assert listing.ok
    _assert_no_forgery(listing.sessions, forged_server)


@requires_tmux
def test_folded_pane_listing_ignores_a_forged_row(forged_server: Path, tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    invalidate_pane_listing(backend.socket_name)
    folded = backend.list_sessions_and_panes(owned_names=set(), owned_instances=None)
    assert folded.panes is not None and folded.panes.ok
    _assert_no_forgery(folded.panes.sessions, forged_server)


def test_older_tmux_output_shape_forges_no_row_without_tmux() -> None:
    escaped_fake = "0\\|999\\|111\\|%99\\|2\\|80\\|24\\|1\\|1\\|7\\|3\\|zvictim\\|zsh\\|x"
    stdout = (
        "P|0|10|111|%1|2|80|24|1|1|8|3|attacker|zsh|/tmp/a\n" + escaped_fake + "\n"
        "P|0|11|111|%2|2|80|24|1|1|7|5|zvictim|sleep|/tmp/v\n"
    )
    _, pane_rows = split_folded_rows("S|$1|1|1|attacker\n" + stdout)
    rows, refused = parse_pane_listing("\n".join(pane_rows))
    by_name = {row["name"]: row for row in rows}
    assert refused == 0 and sorted(by_name) == ["attacker", "zvictim"] and len(rows) == 2
    assert by_name["zvictim"]["pane_dead"] == "0" and by_name["zvictim"]["pid"] == 11
    assert by_name["attacker"]["pane_current_path"] == "/tmp/a\n0|999|111|%99|2|80|24|1|1|7|3|zvictim|zsh|x"


COMMAND_NAME = "x|1|1|%5"


@pytest.fixture
def piped_command_server(tmp_path: Path, tmux_test_socket: str) -> Iterator[Path]:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("no C compiler to build a binary with a | in its name")
    source = tmp_path / "sleeper.c"
    source.write_text("#include <unistd.h>\nint main(void){sleep(60);return 0;}\n")
    binary = tmp_path / COMMAND_NAME
    subprocess.run([compiler, "-o", str(binary), str(source)], check=True, capture_output=True)
    try:
        done = _tmux("new-session", "-d", "-s", ATTACKER, "-c", str(tmp_path), f"'{binary}'")
        assert done.returncode == 0, done.stderr
        yield binary
    finally:
        _tmux("kill-server")


@requires_tmux
def test_a_command_name_holding_the_delimiter_cannot_claim_another_pane_id(
        piped_command_server: Path, tmp_path: Path) -> None:
    for _ in range(40):
        if _tmux("display-message", "-p", "-t", f"={ATTACKER}:", "#{pane_current_command}").stdout.strip() == COMMAND_NAME:
            break
        time.sleep(0.05)
    real = _tmux("display-message", "-p", "-t", f"={ATTACKER}:", "#{pane_pid}|#{session_created}|#{pane_id}").stdout.strip()
    pid, epoch, pane_id = real.split("|")
    listing = _backend(tmp_path)._probe_pane_status_all()
    assert listing.ok and len(listing.sessions) == 1
    row = listing.sessions[0]
    assert row["pane_current_command"] == COMMAND_NAME
    assert (row["pid"], row["created_at_epoch"], row["pane_id"]) == (int(pid), int(epoch), pane_id)


def test_a_line_with_no_delimiter_and_no_row_above_is_refused_not_dropped() -> None:
    assert parse_pane_listing("not a row\n") == ([], 1)
