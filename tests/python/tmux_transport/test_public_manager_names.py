
from __future__ import annotations

import re
from pathlib import Path

from src.core.session_manager import SessionManager

SRC = Path(__file__).resolve().parents[3] / "src"


def test_the_manager_has_one_public_socket_reader() -> None:
    assert callable(SessionManager.tmux_socket_name)
    assert not hasattr(SessionManager, "_tmux_socket_name")


def test_no_module_reaches_for_the_private_socket_reader() -> None:
    pattern = re.compile(r"(?<![A-Za-z0-9])_tmux_socket_name\b")
    offenders = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")
                 if "cplugs/huddle" not in p.as_posix()
                 and any(pattern.search(line) and not line.lstrip().startswith("#")
                         for line in p.read_text(encoding="utf-8").splitlines())]
    assert offenders == []
