
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.core.swarm import memory

MAX_FILES = 400
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 400 * 1024
BASE_FILE = ".base.json"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_path(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\x00" in rel or rel == BASE_FILE:
        raise ValueError(f"unsafe memory path {rel[:60]!r}")
    target = (root / rel).resolve()
    if os.path.commonpath([str(root.resolve()), str(target)]) != str(root.resolve()):
        raise ValueError(f"memory path leaves its folder: {rel[:60]!r}")
    return target


def _walk(root: Path) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    total = 0
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == BASE_FILE or len(out) >= MAX_FILES:
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(raw) > MAX_FILE_BYTES or total + len(raw) > MAX_TOTAL_BYTES:
            continue
        total += len(raw)
        out.append((path.relative_to(root).as_posix(), text))
    return out


def collect(mem: Path) -> List[Dict[str, str]]:
    return [{"path": rel, "sha256": sha(text), "text": text} for rel, text in _walk(mem)]


def write_mirror(mirror: Path, files: List[Dict[str, Any]]) -> None:
    base: Dict[str, str] = {}
    for entry in files[:MAX_FILES]:
        text = entry["text"]
        if sha(text) != entry["sha256"]:
            raise ValueError(f"memory file {entry['path'][:60]!r} does not match its hash")
        memory.refuse_secrets(text, f"mirror/{entry['path']}")
        memory.atomic_write(safe_path(mirror, entry["path"]), text)
        base[entry["path"]] = entry["sha256"]
    mirror.mkdir(parents=True, exist_ok=True)
    memory.atomic_write(mirror / BASE_FILE, json.dumps(base))


def changes(mirror: Path) -> List[Dict[str, Any]]:
    try:
        base = json.loads((mirror / BASE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    now = dict(_walk(mirror))
    out: List[Dict[str, Any]] = []
    for rel, text in now.items():
        if base.get(rel) != sha(text):
            out.append({"path": rel, "base_sha256": base.get(rel), "text": text})
    out.extend({"path": rel, "base_sha256": digest, "deleted": True} for rel, digest in base.items() if rel not in now)
    return out


def apply_writeback(mem: Path, files: List[Dict[str, Any]], machine: str, stamp: str) -> Dict[str, List[str]]:
    applied: List[str] = []
    both: List[str] = []
    for entry in files[:MAX_FILES]:
        target = safe_path(mem, entry["path"])
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        clean = current is None and entry.get("base_sha256") is None or current is not None and sha(current) == entry.get("base_sha256")
        if entry.get("deleted"):
            if clean and target.is_file():
                target.unlink()
                applied.append(entry["path"])
            continue
        text = entry["text"]
        memory.refuse_secrets(text, f"writeback/{entry['path']}")
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"memory file {entry['path'][:60]!r} is over {MAX_FILE_BYTES} bytes")
        if clean:
            memory.atomic_write(target, text)
            applied.append(entry["path"])
        else:
            side = safe_path(mem, f"{entry['path']}.from-{machine}-{stamp}.md")
            memory.atomic_write(side, text)
            both.append(entry["path"])
    return {"applied": applied, "kept_both": both}
