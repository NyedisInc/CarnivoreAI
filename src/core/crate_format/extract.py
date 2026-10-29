
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from src.core.blobcodec.place import PlaceConflict, place_no_clobber, sha256_file
from src.core.crate_format.constants import (
    HOME_CLAUDE, HOME_CODEX, RESUME_CODEX, RESUME_FORK_ONLY, SHARED_ENC, VARIANT_SHARE,
)
from src.core.crate_format.errors import (
    ConversationNotInCrate, CrateCorrupt, CrateMalformed, DestinationInsideHome, DestinationNotEmpty,
)
from src.core.crate_format.model import ConversationRecord
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.names import check_rel
from src.core.crate_format.reader import CrateReader

_PROJECTS = "projects/"


@dataclass
class ExtractResult:

    dest: Path
    files: List[str] = field(default_factory=list)
    enc_folder: Optional[str] = None
    resume_hint: Optional[str] = None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _prepare(dest: Path, forbidden_roots: Sequence[Path]) -> Path:
    dest = Path(dest)
    if os.path.lexists(dest):
        raise DestinationNotEmpty(f"the extract destination {dest.name!r} already exists")
    real = Path(os.path.realpath(dest.parent)) / dest.name
    for root in forbidden_roots:
        if _inside(real, Path(os.path.realpath(root))):
            raise DestinationInsideHome("the extract destination is inside a live harness home")
    os.mkdir(real, 0o700)
    return real


def _write_file(reader: CrateReader, record: FileRecord, dest: Path, rel: str) -> None:
    check_rel(rel)
    target = dest.joinpath(*rel.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = target.parent / f".{target.name[:40]}.{secrets.token_hex(6)}.partial"
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in reader.file_chunks(record):
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if digest.hexdigest() != record.content_sha256:
            raise CrateCorrupt([f"file {record.place!r} does not hash to its recorded sha256"], code="content_mismatch")
        try:
            place_no_clobber(temp, target)
        except PlaceConflict:
            raise CrateMalformed([f"two files of this crate land on {rel!r}"]) from None
    finally:
        temp.unlink(missing_ok=True)
    if sha256_file(target) != record.content_sha256:
        raise CrateCorrupt([f"file {record.place!r} changed on disk after it was written"], code="content_mismatch")
    if record.mtime_ns is not None:
        try:
            os.utime(target, ns=(record.mtime_ns, record.mtime_ns))
        except (OverflowError, ValueError):
            raise CrateMalformed([f"file {record.place!r} has an mtime this platform cannot set"]) from None
    os.chmod(target, (record.mode & 0o777) or 0o600)


def _write_all(reader: CrateReader, plan: Iterable[Tuple[FileRecord, str]], dest: Path,
               forbidden_roots: Sequence[Path]) -> Tuple[Path, List[str]]:
    planned = list(plan)
    for record, rel in planned:
        check_rel(rel)
    real = _prepare(dest, forbidden_roots)
    try:
        for record, rel in planned:
            _write_file(reader, record, real, rel)
    except BaseException:
        shutil.rmtree(real, ignore_errors=True)
        raise
    return real, [rel for _, rel in planned]


def extract_all(reader: CrateReader, dest: Path, forbidden_roots: Sequence[Path] = ()) -> ExtractResult:
    real, files = _write_all(reader, ((rec, rec.place) for rec in reader.files()), dest, forbidden_roots)
    return ExtractResult(real, files)


def _enc_of(conv: ConversationRecord, share: bool, enc_for: Optional[Callable[[str], str]],
            target_cwd: Optional[str]) -> Optional[str]:
    if target_cwd is not None:
        if enc_for is None:
            raise ValueError("target_cwd needs enc_for to name its ENC folder")
        return enc_for(target_cwd)
    if share or conv.working_dir is None:
        return SHARED_ENC
    if enc_for is not None:
        return enc_for(conv.working_dir)
    return conv.enc_folder


def _claude_rel(rec: FileRecord, enc: Optional[str]) -> str:
    if enc is None or not rec.rel.startswith(_PROJECTS):
        return rec.rel
    _, _, rest = rec.rel[len(_PROJECTS):].partition("/")
    return f"{_PROJECTS}{enc}/{rest}"


def _hint(conv: ConversationRecord, share: bool, enc: Optional[str], target_cwd: Optional[str]) -> Optional[str]:
    if conv.family == HOME_CODEX or conv.resume == RESUME_CODEX:
        return None
    if not share:
        return f"claude --resume {conv.id}"
    if target_cwd is not None:
        return f"claude --resume {conv.id} --fork-session"
    return (f"move projects/{enc}/{conv.id}.jsonl (and its folder) into projects/<ENC of your folder>/, then run "
            f"claude --resume {conv.id} --fork-session from that folder")


def extract_conversation(reader: CrateReader, conversation_id: str, dest: Path, *,
                         enc_for: Optional[Callable[[str], str]] = None, forbidden_roots: Sequence[Path] = (),
                         target_cwd: Optional[str] = None) -> ExtractResult:
    conv = reader.manifest.conversation(conversation_id)
    if conv is None:
        raise ConversationNotInCrate(conversation_id)
    share = reader.manifest.variant == VARIANT_SHARE or conv.resume == RESUME_FORK_ONLY
    records = [r for r in reader.files() if r.conversation_id == conversation_id]
    if conv.family == HOME_CODEX:
        enc = None
        plan = [(r, r.rel) for r in records if r.home == HOME_CODEX]
    else:
        enc = _enc_of(conv, share, enc_for, target_cwd)
        plan = [(r, _claude_rel(r, enc)) for r in records if r.home == HOME_CLAUDE]
    if not plan:
        raise ConversationNotInCrate(conversation_id)
    real, files = _write_all(reader, plan, dest, forbidden_roots)
    return ExtractResult(real, files, enc, _hint(conv, share, enc, target_cwd))
