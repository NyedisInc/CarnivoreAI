
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import shutil
import stat
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Tuple

import structlog

from src.cplugs.sdk.safe_io import atomic_write_bytes
from src.cplugs.reviewboard import document, layout, scratch_files, service
from src.cplugs.reviewboard.errors import BadRequest, BoardExists, BoardNotFound, NotScratch, ReadOnlyBoard, StaleSidecar
from src.cplugs.reviewboard.schema import Sidecar

logger = structlog.get_logger()

LOCK_DIR = "locks"
_SLUG = layout.SLUG
Build = Callable[[Optional[Sidecar]], Tuple[Dict[str, Any], Mapping[str, bytes]]]


class NoChange(Exception):
    pass


@contextlib.contextmanager
def locked(state_folder: Path, slug: str) -> Iterator[None]:
    folder = Path(state_folder) / LOCK_DIR
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{slug}.lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_atomic(path: Path, data: bytes) -> None:
    atomic_write_bytes(path, data)


def _member_path(folder: Path, name: str) -> Path:
    if "/" not in name:
        if name in ("", ".", ".."):
            raise BadRequest(f"{name!r} is not a file name")
        return folder / name
    if not scratch_files.MEMBER.fullmatch(name):
        raise BadRequest(f"{name} is not a place a board file may go")
    path = folder
    for part in name.split("/")[:-1]:
        path = path / part
        if not os.path.lexists(path):
            path.mkdir(mode=0o700)
        elif path.is_symlink() or not path.is_dir():
            raise BadRequest(f"{name}: {part} in the board folder is not a real folder")
    return folder / name


def board_folder(root: Path, slug: str) -> Path:
    folder = layout.board_dir(root, slug)
    if folder is None:
        raise BoardNotFound(f"no board {slug} under the boards folder")
    return folder


def _read_current(folder: Path) -> Tuple[Sidecar, bytes]:
    path = folder / document.SIDECAR_FILE
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            raise ReadOnlyBoard(f"{folder.name} has no regular sidecar file")
        data = path.read_bytes()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReadOnlyBoard(f"{folder.name}'s sidecar cannot be read ({type(exc).__name__})") from exc
    if document.is_newer(raw):
        raise ReadOnlyBoard(f"{folder.name} was made by a newer Carnivore and is read only here")
    try:
        return document.parse_sidecar(raw), data
    except document.SidecarInvalid as exc:
        raise ReadOnlyBoard(f"{folder.name} does not validate, so nothing is added to it: {exc.problems[0]}") from exc


def _validated(doc: Dict[str, Any]) -> str:
    try:
        return document.canonical_text(document.parse_sidecar(doc))
    except document.SidecarInvalid as exc:
        raise BadRequest("the board would not validate: " + "; ".join(exc.problems[:5])) from exc


def create(root: Path, state_folder: Path, slug: str, build: Build, parent: Optional[Callable[[], Optional[Path]]] = None) -> Tuple[str, str]:
    if not _SLUG.fullmatch(slug):
        raise BadRequest(f"{slug} is not a board slug")
    with locked(state_folder, slug):
        if os.path.lexists(root / slug) or layout.board_dir(root, slug) is not None:
            raise BoardExists(f"a board {slug} is already there")
        doc, files = build(None)
        text = _validated(doc)
        home = (parent() if parent is not None else None) or root
        target = home / slug
        if os.path.lexists(target):
            raise BoardExists(f"a board {slug} is already there")
        staging = home / f".new-{slug}-{secrets.token_hex(4)}"
        staging.mkdir()
        try:
            for name, data in files.items():
                write_atomic(_member_path(staging, name), data)
            write_atomic(staging / document.SIDECAR_FILE, text.encode("utf-8"))
            os.rename(staging, target)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if os.path.lexists(target):
                raise BoardExists(f"a board {slug} is already there") from exc
            raise
    logger.info("reviewboard_board_created", slug=slug)
    return text, document.etag(text.encode("utf-8"))


def append(root: Path, state_folder: Path, slug: str, base_etag: Optional[str], build: Build) -> Tuple[str, str]:
    folder = board_folder(root, slug)
    with locked(state_folder, slug):
        current, data = _read_current(folder)
        tag = document.etag(data)
        if base_etag is not None and base_etag != tag:
            raise StaleSidecar("the board changed since you read it; read it again", extra={"etag": tag, "sidecar": service.sidecar_json(current)})
        try:
            doc, files = build(current)
        except NoChange:
            return data.decode("utf-8"), tag
        text = _validated(doc)
        named = {v.file for rev in current.revisions for v in rev.views} | scratch_files.named_files(current)
        for name, content in files.items():
            if name in named:
                raise BadRequest(f"{name} belongs to an earlier revision; revision files are immutable")
            write_atomic(_member_path(folder, name), content)
        write_atomic(folder / document.SIDECAR_FILE, text.encode("utf-8"))
    logger.info("reviewboard_board_appended", slug=slug)
    return text, document.etag(text.encode("utf-8"))


_DRAFT_FILE = re.compile(r"draft(--[a-z][a-z0-9-]{0,23})?\.html")


def prune_draft_files(root: Path, state_folder: Path, slug: str) -> int:
    folder = board_folder(root, slug)
    removed = 0
    with locked(state_folder, slug):
        current, _data = _read_current(folder)
        keep = {v.file for v in current.live.draft.views} if current.live else set()
        for entry in sorted(folder.iterdir(), key=lambda p: p.name):
            if not _DRAFT_FILE.fullmatch(entry.name) or entry.name in keep:
                continue
            try:
                if entry.is_symlink() or not entry.is_file():
                    continue
                entry.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("reviewboard_draft_file_left", slug=slug, name=entry.name, error=type(exc).__name__)
    return removed


def remove(root: Path, state_folder: Path, slug: str) -> Dict[str, Any]:
    folder = board_folder(root, slug)
    with locked(state_folder, slug):
        try:
            current, _data = _read_current(folder)
        except ReadOnlyBoard as exc:
            raise NotScratch(f"{slug} cannot be read as a scratch board, so it is not cleared: {exc}") from exc
        if not scratch_files.is_scratch(current):
            raise NotScratch(f"{slug} is a review board, not a scratch board; only a scratch board is cleared")
        entries = [e for rev in current.revisions for e in scratch_files.manifest(rev)]
        gone = folder.with_name(f".gone-{slug}-{secrets.token_hex(4)}")
        os.rename(folder, gone)
        try:
            shutil.rmtree(gone)
        except OSError as exc:
            logger.error("reviewboard_scratch_clear_leftover", slug=slug, path=str(gone), error=type(exc).__name__)
    logger.info("reviewboard_scratch_cleared", slug=slug, revisions=len(current.revisions), files=len(entries))
    return {"slug": slug, "revisions": len(current.revisions), "files": len(entries), "bytes": sum(e["bytes"] for e in entries)}
