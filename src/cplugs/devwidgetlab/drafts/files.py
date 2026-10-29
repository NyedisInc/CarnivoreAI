
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from src.cplugs.devwidgetlab.drafts import store
from src.cplugs.devwidgetlab.errors import DraftInvalid, DraftNotFound

MAX_BYTES = 512 * 1024
AUTHORED_FILES = (store.BRIEF_FILE, "widget.json", "contract.json")
WRITABLE_FOLDERS = ("captures",)


def safe_path(folder: Path, rel: str, *, write: bool = False) -> Path:
    pure = PurePosixPath(rel)
    if not rel or "\x00" in rel or "\\" in rel or pure.is_absolute() or any(part in ("", ".", "..") for part in rel.split("/")):
        raise DraftInvalid(f"not a path inside the draft folder: {rel!r}")
    target = folder.joinpath(*pure.parts)
    probe = folder
    for part in ("", *pure.parts):
        probe = probe / part if part else probe
        if probe.is_symlink():
            raise DraftInvalid("a symbolic link is never followed inside a draft folder")
    if write:
        top = pure.parts[0]
        if rel in AUTHORED_FILES or top in WRITABLE_FOLDERS and len(pure.parts) > 1:
            return target
        if top == store.MIRROR_FOLDER and len(pure.parts) > 1:
            store.mirror_target(PurePosixPath(*pure.parts[1:]).as_posix())
            return target
        raise DraftInvalid(f"{rel} is generated or outside what a draft author writes (BRIEF.md, widget.json, contract.json, captures/, files/web/src/...)")
    return target


def list_files(folder: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if p.is_file() and not p.is_symlink() and not any((folder / q).is_symlink() for q in rel.parents if str(q) != "."):
            out.append({"path": rel.as_posix(), "bytes": p.stat().st_size})
    return out


def read_file(folder: Path, rel: str) -> Dict[str, Any]:
    target = safe_path(folder, rel)
    if not target.is_file():
        raise DraftNotFound(f"no file {rel} in this draft")
    if target.stat().st_size > MAX_BYTES:
        raise DraftInvalid(f"{rel} is larger than {MAX_BYTES} bytes")
    try:
        return {"path": rel, "content": target.read_text(encoding="utf-8"), "bytes": target.stat().st_size}
    except UnicodeDecodeError as exc:
        raise DraftNotFound(f"{rel} is not a text file") from exc


def write_file(folder: Path, rel: str, content: str) -> Dict[str, Any]:
    target = safe_path(folder, rel, write=True)
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise DraftInvalid(f"a file is at most {MAX_BYTES} bytes")
    if rel.endswith(".json"):
        try:
            if not isinstance(json.loads(content), dict):
                raise ValueError("not an object")
        except ValueError as exc:
            raise DraftInvalid(f"{rel} must be a JSON object") from exc
    created = not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or any(p.is_symlink() for p in target.parents if p.is_relative_to(folder)):
        raise DraftInvalid("a symbolic link is never followed inside a draft folder")
    target.write_bytes(data)
    _after_change(folder, rel)
    return {"path": rel, "bytes": len(data), "created": created}


def delete_file(folder: Path, rel: str) -> Dict[str, Any]:
    target = safe_path(folder, rel, write=True)
    if not target.is_file():
        raise DraftNotFound(f"no file {rel} in this draft")
    target.unlink()
    _after_change(folder, rel)
    return {"path": rel, "deleted": True}


def _after_change(folder: Path, rel: str) -> None:
    if rel.startswith(store.MIRROR_FOLDER + "/"):
        store.write_overrides_note(folder, store.read_record(folder))
