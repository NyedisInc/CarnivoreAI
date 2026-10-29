
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

import structlog

from src.cplugs.devwidgetlab.capture import REPO, SCRIPT  # noqa: F401
from src.cplugs.devwidgetlab.drafts import checkout, renames
from src.cplugs.devwidgetlab.errors import DraftExists, DraftInvalid, DraftNotFound, NoCheckout
from src.cplugs.sdk import app_info

logger = structlog.get_logger()

DRAFTS_FOLDER = "drafts"
DISCARDED_FOLDER = ".discarded"
RECORD_FILE = "draft.json"
BRIEF_FILE = "BRIEF.md"
OVERRIDES_FILE = "OVERRIDES.md"
MIRROR_FOLDER = "files"
BUILD_FOLDER = "build"
SCHEMA = 1
KINDS = ("new", "revision")
STATES = ("starter", "working", "building", "built", "failed")
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
MIRROR_ROOTS = ("web/src/",)
MAX_LIVE_DRAFTS = 12


def checkout_available(storage_path: Path) -> bool:
    return checkout.resolve(storage_path) is not None


def require_checkout(storage_path: Path) -> Path:
    root = checkout.resolve(storage_path)
    if root is None:
        raise NoCheckout(checkout.NO_FOLDER_MESSAGE)
    return root


def storage_of(folder: Path) -> Path:
    return Path(folder).parent.parent


def root_of(folder: Path) -> Path:
    return require_checkout(storage_of(folder))


def drafts_dir(storage_path: Path) -> Path:
    return Path(storage_path) / DRAFTS_FOLDER


def check_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG_PATTERN.match(slug) or slug.endswith("-"):
        raise DraftInvalid("a draft name is lowercase letters, digits and hyphens, starting with a letter (2 to 40 characters)")
    return slug


def draft_dir(storage_path: Path, slug: str) -> Path:
    return drafts_dir(storage_path) / check_slug(slug)


def existing_dir(storage_path: Path, slug: str) -> Path:
    folder = draft_dir(storage_path, slug)
    if not (folder / RECORD_FILE).is_file():
        raise DraftNotFound(f"no draft {slug}")
    return folder


def mirror_target(rel: str) -> str:
    pure = PurePosixPath(rel)
    if not rel or "\\" in rel or pure.is_absolute() or ".." in pure.parts or not rel.startswith(MIRROR_ROOTS):
        raise DraftInvalid(f"a draft file maps to a path under {' or '.join(MIRROR_ROOTS)}, got {rel!r}")
    return str(pure)


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_record(folder: Path) -> Dict[str, Any]:
    try:
        record = json.loads((folder / RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DraftNotFound(f"draft record unreadable: {folder.name}") from exc
    return renames.current_record(record) if isinstance(record, dict) else record


def mirrored_files(folder: Path) -> List[str]:
    root = folder / MIRROR_FOLDER
    if not root.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def write_overrides_note(folder: Path, record: Dict[str, Any]) -> None:
    repo = root_of(folder)
    lines = [f"# {record['slug']}: what this draft changes", "",
             f"kind: {record['kind']} / widget: {record['widget']} / base: {record.get('base_sha') or 'unknown'}", ""]
    for rel in mirrored_files(folder):
        lines.append(f"- {'overrides' if (repo / rel).is_file() else 'adds'} `{rel}`")
    if len(lines) == 4:
        lines.append("(no files changed yet)")
    (folder / OVERRIDES_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_build(folder: Path) -> Dict[str, Any]:
    try:
        return json.loads((folder / BUILD_FOLDER / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "none", "sha": None, "built_at": None, "log": None, "error": ""}


def read_manifest(folder: Path) -> Dict[str, Any] | None:
    try:
        value = json.loads((folder / "widget.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def build_stale(build: Dict[str, Any], root: Path, head: str) -> bool:
    if build.get("state") != "built" or not build.get("sha") or not head:
        return False
    return build["sha"] != head or (bool(build.get("root")) and build["root"] != str(root))


def summary(folder: Path) -> Dict[str, Any]:
    record = read_record(folder)
    build = read_build(folder)
    root = root_of(folder)
    head = head_sha(root)
    return {**record, "files": mirrored_files(folder), "build": build, "manifest": read_manifest(folder),
            "stale": bool(record.get("base_sha")) and record.get("base_sha") != head,
            "build_stale": build_stale(build, root, head),
            "code": {"app": checkout.app_sha(), "build": build.get("sha") or "", "source": head}}


def list_drafts(storage_path: Path) -> List[Dict[str, Any]]:
    root = drafts_dir(storage_path)
    out: List[Dict[str, Any]] = []
    for folder in (sorted(root.iterdir()) if root.is_dir() else []):
        if folder.name.startswith(".") or not folder.is_dir():
            continue
        try:
            out.append(summary(folder))
        except DraftNotFound as exc:
            logger.warning("widget_lab_draft_unreadable", folder=folder.name, error=str(exc))
    return sorted(out, key=lambda d: d.get("created", ""), reverse=True)


def head_sha(repo: Path) -> str:
    if not app_info.git_available():
        return ""
    try:
        done = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("widget_lab_head_sha_failed", error_type=type(exc).__name__)
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def create_record(storage_path: Path, slug: str, kind: str, widget: str, title: str) -> Path:
    if kind not in KINDS:
        raise DraftInvalid(f"kind is one of {', '.join(KINDS)}")
    repo = require_checkout(storage_path)
    folder = draft_dir(storage_path, slug)
    if folder.exists():
        raise DraftExists(f"a draft named {slug} already exists")
    if len(list_drafts(storage_path)) >= MAX_LIVE_DRAFTS:
        raise DraftInvalid(f"at most {MAX_LIVE_DRAFTS} drafts at a time; discard one first")
    (folder / MIRROR_FOLDER).mkdir(parents=True)
    (folder / "captures").mkdir()
    record = {"schema": SCHEMA, "slug": slug, "kind": kind, "widget": widget, "title": title.strip()[:80] or slug,
              "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "state": "starter", "base_sha": head_sha(repo), "session": None}
    write_json(folder / RECORD_FILE, record)
    return folder


def set_fields(folder: Path, **fields: Any) -> Dict[str, Any]:
    if "state" in fields and fields["state"] not in STATES:
        raise DraftInvalid(f"state is one of {', '.join(STATES)}")
    record = {**read_record(folder), **fields}
    write_json(folder / RECORD_FILE, record)
    return record


def discard(storage_path: Path, slug: str) -> Path:
    folder = existing_dir(storage_path, slug)
    target = drafts_dir(storage_path) / DISCARDED_FOLDER / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(target))
    logger.info("widget_lab_draft_discarded", slug=slug, to=str(target))
    return target
