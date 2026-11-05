from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MANUAL = ROOT / "tests" / "manual"


def test_every_manual_harness_script_tag_names_a_file_that_exists() -> None:
    missing: list[str] = []
    for page in MANUAL.glob("*.html"):
        for src in re.findall(r'<script[^>]+src="(\.\./\.\./client/js/[^"?#]+)', page.read_text(encoding="utf-8")):
            if not (page.parent / src).resolve().is_file():
                missing.append(f"{page.name} -> {src}")
    assert not missing, missing


def test_active_verify_scripts_import_only_sibling_modules_that_exist() -> None:
    bad: list[str] = []
    for script in SCRIPTS.glob("verify_*.py"):
        for mod in re.findall(r"^from (verify_\w+) import", script.read_text(encoding="utf-8"), re.M):
            if not (SCRIPTS / f"{mod}.py").is_file():
                bad.append(f"{script.name} imports {mod}")
    assert not bad, bad
