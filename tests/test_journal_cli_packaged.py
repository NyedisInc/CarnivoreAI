
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = "scripts/session_journal.py"


def test_the_cli_is_bundled():
    data = json.loads((ROOT / "macOS" / "package.json").read_text())
    entries = {(e.get("from"), e.get("to")) for e in data["build"]["extraResources"] if isinstance(e, dict)}
    assert (f"../{CLI}", CLI) in entries


def test_the_cli_is_resynced_into_its_own_directory():
    text = (ROOT / "macOS" / "bootstrap.js").read_text()
    block = re.search(r"const RESYNC_ALLOWLIST\s*=\s*\[(.*?)\];", text, re.DOTALL).group(1)
    assert f"name: '{CLI}', isDir: false" in block
    body = text[text.index("function syncBundledAssets"):]
    assert "fs.mkdirSync(path.dirname(dst), { recursive: true });" in body, \
        "a nested file copy needs its directory; copyFileSync does not make it"


def test_the_cli_finds_src_from_its_own_location():
    text = (ROOT / CLI).read_text()
    assert "Path(__file__).resolve().parent.parent" in text
    assert (ROOT / CLI).exists()
