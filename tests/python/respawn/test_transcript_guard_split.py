
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from src.core import session_respawn

SHARED_FILE_LINES = 1000
ROOT = Path(__file__).resolve().parents[3]


def test_session_respawn_is_under_the_shared_split_line() -> None:
    lines = (ROOT / "src" / "core" / "session_respawn.py").read_text(encoding="utf-8").count("\n")
    assert lines <= SHARED_FILE_LINES, f"session_respawn.py is {lines} lines"


def test_the_transcript_guard_lives_in_its_own_module_with_no_alias() -> None:
    from src.core.respawn import transcript_guard as respawn_transcript_guard

    assert respawn_transcript_guard.refuse_if_transcript_missing.__module__ == "src.core.respawn.transcript_guard"
    assert not hasattr(session_respawn, "refuse_if_transcript_missing")
    stale: List[str] = []
    for folder in ("src", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "refuse_if_transcript_missing" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.ImportFrom) and node.module == "src.core.session_respawn" and any(a.name == "refuse_if_transcript_missing" for a in node.names):
                    stale.append(str(path.relative_to(ROOT)))
    assert stale == []
