
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.cplugs.devwidgetlab.drafts import create


def new_draft(storage: Path, name: str = "Pulse board") -> Dict[str, Any]:
    return create.create_new(storage, name, "shows a pulse\nsecond line", ["home", "terminal"], ["small", "wide"], "tools")


def fake_repo(root: Path) -> Path:
    (root / "src" / "data").mkdir(parents=True)
    for name in ("widgets.json", "widget-contracts.json"):
        (root / "src" / "data" / name).write_text(json.dumps({"schema": 1, "widgets": [{"id": "core.notes"}]}, indent=2) + "\n")
    cell = root / "web" / "src" / "opscenter" / "cells" / "notes" / "Cell.svelte"
    cell.parent.mkdir(parents=True)
    cell.write_text("<p>old</p>")
    return root
