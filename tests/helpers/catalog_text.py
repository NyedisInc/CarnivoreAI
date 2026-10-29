
from __future__ import annotations

from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "client" / "js" / "i18n" / "catalog.en.js"
PLUGINS_WEB = REPO_ROOT / "web" / "src" / "cplugs"
SLICE_NAME = "catalog.en.js"
PLUGINS_SRC = REPO_ROOT / "src" / "cplugs"
NOTIFY_SLICE_NAME = "notify.catalog.en.js"


def slice_paths() -> Dict[str, Path]:
    return {p.parent.name: p for p in sorted(PLUGINS_WEB.glob(f"*/{SLICE_NAME}"))}


def notify_slice_paths() -> Dict[str, Path]:
    return {p.parent.name: p for p in sorted(PLUGINS_SRC.glob(f"*/{NOTIFY_SLICE_NAME}"))}


def catalog_text() -> str:
    parts = [CATALOG_PATH.read_text(encoding="utf-8")]
    parts.extend(p.read_text(encoding="utf-8") for p in (*slice_paths().values(), *notify_slice_paths().values()))
    return "\n".join(parts)
