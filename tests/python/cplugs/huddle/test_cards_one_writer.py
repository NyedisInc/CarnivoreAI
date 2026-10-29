
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterator, List

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
ALLOWED = {SRC / "cplugs/huddle/cards/flow.py", SRC / "cplugs/huddle/cards/policy.py",
           SRC / "cplugs/huddle/cards/state_log.py", SRC / "core/pack/migrate/task_manager_history.py"}
FROZEN_LADDER = SRC / "core" / "work" / "ladder"

ITEM_WRITE = re.compile(r"(?:UPDATE\s+work_items\s+SET|REPLACE\s+INTO\s+work_items|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+work_items)\b[^;]*?\bcard_", re.I | re.S)
TABLE_WRITE = re.compile(r"\b(?:INSERT|REPLACE|UPDATE|DELETE)\b[^;]*?\bwork_card_(?:events|rules|grants|deals|suggestions)\b", re.I | re.S)


def _literals(text: str) -> Iterator[str]:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            yield "".join(part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)


def offenders(text: str) -> List[str]:
    literals = list(_literals(text))
    return [name for name, pattern in (("item card column", ITEM_WRITE), ("card table", TABLE_WRITE))
            if any(pattern.search(lit) for lit in literals)]


def test_only_flow_and_policy_write_card_columns_and_tables():
    found = [str(path.relative_to(ROOT)) + ": " + ", ".join(hits) for path in sorted(SRC.rglob("*.py"))
             if path not in ALLOWED and FROZEN_LADDER not in path.parents and (hits := offenders(path.read_text()))]
    assert not found, ("these files write card columns or card tables outside cards/flow.py and cards/policy.py:\n  "
                       + "\n  ".join(found))


def test_the_two_writers_still_carry_the_patterns_so_the_check_can_go_red():
    assert "item card column" in offenders((SRC / "cplugs/huddle/cards/flow.py").read_text())
    assert "card table" in offenders((SRC / "cplugs/huddle/cards/flow.py").read_text())
    assert "card table" in offenders((SRC / "cplugs/huddle/cards/policy.py").read_text())
    assert offenders('conn.execute("UPDATE work_items SET card_holder = 3 WHERE id = 1")') == ["item card column"]
    assert offenders('conn.execute("DELETE FROM work_card_events WHERE id = 1")') == ["card table"]
    assert offenders('c.execute("update work_items set card_holder = 3 where id = 1")') == ["item card column"]
    assert offenders('c.execute("REPLACE INTO work_items (id, card_holder) VALUES (1, 2)")') == ["item card column"]
    assert offenders('c.execute("INSERT INTO work_items (list_key, card_parent) VALUES (?, ?)")') == ["item card column"]
    assert offenders('c.execute("UPDATE work_items SET text = ?, " "card_mark = ? WHERE id = 1")') == ["item card column"]
    assert offenders('c.execute(f"UPDATE work_items SET {sets}, card_mark = ?")') == ["item card column"]
    assert offenders('c.execute("replace into work_card_deals VALUES (1)")') == ["card table"]
    assert offenders('c.execute("UPDATE work_items SET text = ? WHERE id = ?")\nok = flow.card_shaped(row)') == []
    assert offenders('c.execute(f"UPDATE work_items SET claude_working = 1 WHERE id = ? AND {flow.UNHELD_SQL}")') == []
    assert offenders((FROZEN_LADDER / "cards_rung.py").read_text()) == []
    assert len(list(SRC.rglob("*.py"))) > 500
