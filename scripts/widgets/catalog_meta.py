
from __future__ import annotations

import datetime
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from typing import Any

CATALOG_META_SCHEMA = 1
CATALOG_META_FILE = "capture.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CATALOG_FIXTURE, CATALOG_HOST = "data", "home"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


def png_facts(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    pixels = list(struct.unpack(">II", data[16:24])) if data.startswith(PNG_SIGNATURE) and len(data) >= 24 else None
    return {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "pixels": pixels}


def write_catalog_metadata(folder: Path, widget: str, theme: str) -> Path | None:
    shots = sorted(folder.glob("*.png"))
    if not shots:
        return None
    repo = folder.resolve().parents[3]
    meta = {"schema": CATALOG_META_SCHEMA, "widget": widget, "host": CATALOG_HOST, "theme": theme, "fixture": CATALOG_FIXTURE,
            "source_revision": {"sha": _git(repo, "rev-parse", "HEAD"),
                                "dirty": bool(_git(repo, "status", "--porcelain", "--", "web/src", "src", "client"))},
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "images": [png_facts(p) for p in shots], "pipeline": "scripts/widgets (Widget Lab)"}
    path = folder / CATALOG_META_FILE
    path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return path
