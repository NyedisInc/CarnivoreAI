from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
EXEMPT_DIRS = ("lib", "archive")
KNOWN_LOCAL_REPORTS = frozenset({
    "scripts/backup/verify_set.py",
    "scripts/gate/default_state.py",
    "scripts/maintenance/reap_orphan_agent_processes.py",
    "scripts/verify_asleep_unread_moon.py",
    "scripts/verify_home_header_span.py",
    "scripts/verify_layout_zoom.py",
    "scripts/verify_layouts_migration.py",
    "scripts/verify_layouts_page.py",
    "scripts/verify_load_stray_led.py",
    "scripts/verify_new_tab_menu_projects.py",
    "scripts/verify_terminal_tabs.py",
})


def _is_python(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.suffix:
        return False
    try:
        with path.open("rb") as fh:
            first = fh.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def scripts_with_local_report(root: Path) -> set[str]:
    found: set[str] = set()
    for path in sorted(p for p in (root / "scripts").rglob("*") if p.is_file() and _is_python(p)):
        rel = path.relative_to(root)
        if rel.parts[1] in EXEMPT_DIRS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(isinstance(n, ast.ClassDef) and n.name == "Report" for n in ast.walk(tree)):
            found.add(rel.as_posix())
    return found


def test_no_new_local_report_class() -> None:
    new = scripts_with_local_report(ROOT) - KNOWN_LOCAL_REPORTS
    assert not new, f"use scripts.lib.verify_harness.Report instead of a local class: {sorted(new)}"


def test_known_list_has_no_stale_entries() -> None:
    stale = KNOWN_LOCAL_REPORTS - scripts_with_local_report(ROOT)
    assert not stale, f"remove from KNOWN_LOCAL_REPORTS (already migrated): {sorted(stale)}"


def test_scan_goes_red_on_a_new_local_report(tmp_path: Path) -> None:
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    (tmp_path / "scripts" / "verify_new.py").write_text("class Report:\n    pass\n")
    (tmp_path / "scripts" / "lib" / "shared.py").write_text("class Report:\n    pass\n")
    (tmp_path / "scripts" / "tool").write_text("#!/usr/bin/env python3\nclass Report:\n    pass\n")
    (tmp_path / "scripts" / "other.sh").write_text("class Report:\n")
    assert scripts_with_local_report(tmp_path) == {"scripts/verify_new.py", "scripts/tool"}
