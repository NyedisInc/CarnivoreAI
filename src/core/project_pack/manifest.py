
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from src.core.safe_io.atomic_write import atomic_write_bytes
from src.core.project_pack import constants as K
from src.core.project_pack.inventory import Entry
from src.core.trail_entry import utc_now


class ManifestError(Exception):
    pass


def write_atomic(path: str, data: bytes) -> None:
    atomic_write_bytes(path, data)


def write_sidecar(root: str, archive_name: str, archive_sha256: str, archive_bytes: int, entries: List[Entry],
                  level: int) -> None:
    doc: Dict[str, Any] = {
        "format": K.MANIFEST_FORMAT, "created_at": utc_now(), "tool": "carnivore project_pack",
        "archive": {"name": archive_name, "sha256": archive_sha256, "bytes": archive_bytes,
                    "compression": f"zstd level {level}, pax tar, macOS bsdtar"},
        "xattrs": False, "root_name": os.path.basename(root),
        "entry_columns": ["path", "kind", "size", "mode", "mtime_ns", "link", "sha256", "group"],
        "entries": [e.as_row() for e in entries],
    }
    write_atomic(os.path.join(root, K.MANIFEST_NAME), json.dumps(doc, separators=(",", ":")).encode("utf-8"))


def read_sidecar(root: str) -> Tuple[Dict[str, Any], List[Entry]]:
    path = os.path.join(root, K.MANIFEST_NAME)
    try:
        with open(path, "rb") as handle:
            doc = json.load(handle)
        if doc.get("format") != K.MANIFEST_FORMAT:
            raise ManifestError(f"unknown manifest format {doc.get('format')!r}")
        return doc, [Entry.from_row(r) for r in doc["entries"]]
    except (OSError, ValueError, KeyError, IndexError) as exc:
        raise ManifestError(f"the manifest {K.MANIFEST_NAME} cannot be read: {exc}") from exc


def write_readme(root: str, archive_name: str) -> None:
    text = (
        "This folder was packed by Carnivore to save disk space.\n\n"
        f"The whole project is in {archive_name} (zstd-compressed tar, readable by macOS's own tar).\n"
        f"{K.MANIFEST_NAME} lists every file with its sha256.\n\n"
        "To unpack with Carnivore: open the project (show hidden projects) and choose unpack folder.\n"
        "To unpack by hand, in a terminal:\n\n"
        f"  cd \"{root}\"\n"
        f"  /usr/bin/tar -xpf \"{archive_name}\"\n\n"
        "Then move the three pack files to the Trash.\n"
    )
    write_atomic(os.path.join(root, K.README_NAME), text.encode("utf-8"))
