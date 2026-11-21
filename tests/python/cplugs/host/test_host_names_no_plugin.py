
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parents[4]
HOST = ROOT / "src" / "plugins" / "host"
ALSO = {"reviewboard", "publicboard"}
KNOWN: Dict[str, Set[str]] = {
    "activity_reader.py": {"huddle"},
    "identity.py": {"huddle", "save", "share", "unread"},
    "legacy_disabled.py": {"share", "unread"},
    "session_fields.py": {"unread"},
    "sidecar_page.py": {"flow"},
    "split_migration.py": {"save"},
    "swarm_default_migration.py": {"huddle"},
    "system_lifecycle.py": {"share"},
}


def plugin_ids() -> Set[str]:
    base = ROOT / "src" / "plugins"
    return {p.parent.name for p in base.glob("*/cplug.json")} | ALSO


def named_in(text: str, ids: Set[str]) -> Set[str]:
    found: Set[str] = set()
    for line in text.splitlines():
        if line.strip().startswith("#") or "Example:" in line:
            continue
        found |= {i for i in ids if re.search(rf"""["']{re.escape(i)}["']""", line)}
    return found


def test_the_host_names_no_plugin_outside_the_known_older_reaches() -> None:
    ids = plugin_ids()
    new = {}
    for path in sorted(HOST.rglob("*.py")):
        extra = named_in(path.read_text(encoding="utf-8"), ids) - KNOWN.get(path.name, set())
        if extra:
            new[path.name] = sorted(extra)
    assert new == {}, "host code names a plugin; the plugin declares it in its manifest or data block instead"


def test_the_scan_can_fail() -> None:
    assert named_in('FILLED = (("reviewboard", "boards"),)', {"reviewboard"}) == {"reviewboard"}
    assert named_in('# "reviewboard"\nx = 1  # Example: "reviewboard"', {"reviewboard"}) == set()
