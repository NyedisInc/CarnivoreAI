
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.widgets.common import png_dimensions, source_revision

CATALOG_META_SCHEMA = 1
CATALOG_META_FILE = "capture.json"
CATALOG_FIXTURE, CATALOG_HOST = "data", "home"


def png_facts(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    dims = png_dimensions(data)
    pixels = list(dims) if dims else None
    return {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "pixels": pixels}


def write_catalog_metadata(folder: Path, widget: str, theme: str) -> Path | None:
    shots = sorted(folder.glob("*.png"))
    if not shots:
        return None
    repo = folder.resolve().parents[3]
    meta = {"schema": CATALOG_META_SCHEMA, "widget": widget, "host": CATALOG_HOST, "theme": theme, "fixture": CATALOG_FIXTURE,
            "source_revision": source_revision(repo),
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "images": [png_facts(p) for p in shots], "pipeline": "scripts/widgets (Widget Lab)"}
    path = folder / CATALOG_META_FILE
    path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return path
