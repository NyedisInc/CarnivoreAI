from __future__ import annotations

import json
import sqlite3

import pytest

from src.cplugs.huddle import answers, files, rich_ask


def _matches(parts: str) -> bool:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE work_messages (parts TEXT)")
    conn.execute("INSERT INTO work_messages VALUES (?)", (parts,))
    return conn.execute(f"SELECT 1 FROM work_messages WHERE {files.PARTS_SQL}").fetchone() is not None


ENTRY = {"id": "abcdef01", "name": "a.png", "mime": "image/png", "size": 3, "path": "1/abcdef01-a.png"}


def test_the_answers_prefix_is_what_the_writers_actually_emit() -> None:
    assert answers.dump(7, {"q": "x"}).startswith(rich_ask.ANSWERS_TO_PREFIX)
    assert json.dumps({"v": rich_ask.VERSION, "answers_to": 7}).startswith(files.FREEFORM_PREFIX)


@pytest.mark.parametrize("stored", [
    {"files": [ENTRY]},
    {"v": rich_ask.VERSION, "answers_to": 3, "freeform": True, "files": [ENTRY]},
    {"quote": "q", "files": [ENTRY]},
])
def test_every_parts_writer_with_files_is_found_by_the_orphan_sweep_query(stored: dict) -> None:
    raw = json.dumps(stored, ensure_ascii=False)
    assert _matches(raw)
    assert files.entries_of(raw)


def test_no_module_spells_the_parts_version_literally() -> None:
    from pathlib import Path

    root = Path(files.__file__).parent
    spelled = [p.name for p in root.glob("*.py") if p.name != "rich_ask.py" and any("'{\"v\": 2" in line or "{{\"v\": 2" in line or '{\\"v\\": 2' in line for line in p.read_text().splitlines())]
    assert spelled == [], spelled
