
from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "release" / "preview-install.sh"


def test_the_script_exists_so_the_check_can_fail() -> None:
    assert "to_trash" in SCRIPT.read_text(encoding="utf-8")


def test_no_call_sends_files_to_the_boot_trash() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    calls = [line for line in text.splitlines() if re.search(r'\b(to_trash|mv)\b.*\$HOME/\.Trash', line)]
    assert calls == []


def test_the_built_dmg_is_moved_out_not_copied() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'mv "$built" "$OUT_DIR/.$name.partial"' in text
    assert 'cp "$built" "$OUT_DIR/.$name.partial"' not in text
