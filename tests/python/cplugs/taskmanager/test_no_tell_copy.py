
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CATALOG = ROOT / "client" / "js" / "i18n" / "catalog.en.js"
GUIDE = ROOT / "src" / "core" / "skills" / "bundled" / "huddle" / "SKILL.md"
INSTRUCTIONS = ROOT / "src" / "core" / "mcp" / "instructions.py"
WORD = re.compile(r"\b(tell|tells|told|telling)\b", re.I)
OTHERS = ("cplug.huddle.swarm.", "cplug.huddle.chat.")
ALLOWED = ("tell the huddle, not the terminal", "could not tell your project")
ENTRY = re.compile(r"^\s*'(cplug\.huddle\.[^']+)':\s*(.*?),?\s*$")


def _task_manager_values() -> dict:
    found = {}
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        match = ENTRY.match(line)
        if match and not match.group(1).startswith(OTHERS):
            found[match.group(1)] = match.group(2)
    return found


def test_the_catalog_check_looks_at_the_task_managers_values():
    values = _task_manager_values()
    assert len(values) > 400 and "cplug.huddle.send.send" in values


def test_no_task_manager_catalog_value_says_tell_or_told():
    bad = {k: v for k, v in _task_manager_values().items() if WORD.search(v)}
    assert bad == {}, f"say send, not tell (R3): {bad}"


def test_the_word_check_can_go_red():
    assert WORD.search("enter adds and tells claude") and WORD.search("the session is told then")
    assert not WORD.search("enter adds and sends to claude") and not WORD.search("a retell")


def test_the_agent_facing_words_say_send():
    text = GUIDE.read_text(encoding="utf-8")
    for allowed in ALLOWED:
        text = text.replace(allowed, "")
    assert [m.group(0) for m in WORD.finditer(text)] == [], "the bundled guide still says tell"
    channel = INSTRUCTIONS.read_text(encoding="utf-8").split("_CHANNEL_RULES")[1].split('"""')[1]
    assert not WORD.search(channel) and "send to claude" in channel
