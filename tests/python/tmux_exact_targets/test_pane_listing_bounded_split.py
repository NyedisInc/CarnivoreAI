
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterator

import pytest

from src.core.tmux_backend import TmuxBackend
from src.core.tmux_transport.pane_listing import PANE_LISTING_FORMAT, parse_pane_listing
from tests.socket_guard import derive_test_socket


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", *args], capture_output=True,
                          text=True, check=False)


@pytest.fixture()
def hostile_socket(tmp_path: Path) -> Iterator[str]:
    socket = derive_test_socket("bounded_split")
    folder = tmp_path / "a|b"
    folder.mkdir()
    for name, cwd in (("api|prod", tmp_path), ("plain", folder), ("café|€", tmp_path)):
        assert _tmux(socket, "new-session", "-d", "-s", name, "-c", str(cwd), "sleep 120").returncode == 0
    try:
        yield socket
    finally:
        _tmux(socket, "kill-server")


@pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")
def test_real_tmux_rows_keep_each_field_in_its_own_place(hostile_socket: str, tmp_path: Path) -> None:
    backend = TmuxBackend.for_external(session_name="plain", working_dir=tmp_path, on_output=None,
                                       socket_name=hostile_socket)
    rows = {r["name"]: r for r in backend.list_pane_status_all(fresh=True).sessions}
    assert set(rows) == {"api|prod", "plain", "café|€"}
    assert all(r["pane_dead"] == "0" and r["status"] == "running" for r in rows.values())
    assert rows["plain"]["pane_current_path"].endswith("a|b")
    assert all(isinstance(r["pid"], int) and r["pane_id"].startswith("%") for r in rows.values())


def test_a_lying_name_cannot_move_a_field() -> None:
    name, command, path = "x|0|zsh|1", "claude", "/p|q"
    fixed = "0|4242|1755000000|%3|1755000001|80|24|1|1"
    line = f"{fixed}|{len(name.encode())}|{len(command.encode())}|{name}|{command}|{path}"
    rows, refused = parse_pane_listing(line + "\n")
    (row,) = rows
    assert refused == 0
    assert (row["name"], row["pane_current_command"], row["pane_current_path"]) == (name, command, path)
    assert (row["pid"], row["created_at_epoch"], row["pane_id"], row["pane_width"]) == (4242, 1755000000, "%3", 80)


def test_a_row_whose_length_disagrees_with_its_text_is_refused() -> None:
    line = "0|4242|1755000000|%3|1755000001|80|24|1|1|99|4|short|zsh|/p"
    assert parse_pane_listing(line + "\n") == ([], 1)


def test_the_format_leads_with_tmux_generated_fields() -> None:
    head = PANE_LISTING_FORMAT.split("|")[:9]
    assert not any(token in "".join(head) for token in ("session_name", "pane_current"))


def test_a_refused_row_makes_the_listing_incomplete_not_empty() -> None:
    rows, refused = parse_pane_listing("0|4|1|%1|2|80|24|1|1||||s|zsh|/p\nnot a row\n")
    assert rows == [] and refused == 1
