
from __future__ import annotations

import json
import os
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterable, List, Optional, Tuple

import structlog

from src.core.bookmarks.errors import TranscriptChanged, TranscriptUnavailable
from src.core.bookmarks.transcript_index import SKIPPED_IN_COPY, Node, TranscriptIndex

logger = structlog.get_logger()


def _read_span(stream: BinaryIO, offset: int, length: int) -> dict:
    stream.seek(offset)
    raw = stream.read(length)
    try:
        record = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TranscriptChanged("the transcript changed while it was being copied; try again") from exc
    if not isinstance(record, dict):
        raise TranscriptChanged("the transcript changed while it was being copied; try again")
    return record


def _line(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def copied_record(record: dict, *, new_session: str, source_session: str, parent: Optional[str]) -> dict:
    out = {k: v for k, v in record.items() if k != "sessionKind"}
    out.update(sessionId=new_session, parentUuid=parent, isSidechain=False,
               forkedFrom={"sessionId": source_session, "messageUuid": record.get("uuid")})
    if "session_id" in out:
        out["session_id"] = new_session
    return out


def _messages(stream: BinaryIO, chain: List[Node], new_session: str, source_session: str) -> Iterable[bytes]:
    parent: Optional[str] = None
    for node in chain:
        if node.kind == SKIPPED_IN_COPY:
            continue
        record = _read_span(stream, node.offset, node.length)
        if record.get("uuid") != node.uuid:
            raise TranscriptChanged("the transcript changed while it was being copied; try again")
        yield _line(copied_record(record, new_session=new_session, source_session=source_session, parent=parent))
        parent = node.uuid


def _carried(stream: BinaryIO, index: TranscriptIndex, new_session: str, source_session: str) -> Iterable[bytes]:
    replacements: list = []
    last: dict = {}
    modes: List[dict] = []
    for kind, offset, length in index.carried:
        record = _read_span(stream, offset, length)
        if record.get("sessionId") not in (None, source_session):
            continue
        if kind == "content-replacement" and isinstance(record.get("replacements"), list):
            replacements.extend(record["replacements"])
        elif kind == "memory-mode":
            modes.append(record)
        else:
            last[kind] = record
    if replacements:
        yield _line({"type": "content-replacement", "sessionId": new_session, "replacements": replacements})
    for record in ([last["relocated"]] if "relocated" in last else []) + modes + (
            [last["atis-latch"]] if "atis-latch" in last else []):
        yield _line({**record, "sessionId": new_session})


def write_copy(index: TranscriptIndex, chain: List[Node], dest_dir: Path,
               new_session: Optional[str] = None) -> Tuple[str, Path]:
    """Write the cut copy of ``index``'s transcript, keeping ``chain``. BLOCKING.

    Inputs: index (TranscriptIndex) - the source's graph; chain (list[Node]) - from
      ``cut.kept_chain``; dest_dir (Path) - the project directory (created 0700 if missing);
      new_session (str | None) - the new conversation uuid (a fresh uuid4 by default).
    Output: (new conversation uuid, path of the new transcript).
    Raises: TranscriptUnavailable - nothing to copy, or the destination could not be written;
      TranscriptChanged - the source moved underneath; FileExistsError never escapes (a fresh
      uuid collides only by a broken RNG, and is reported as unavailable).
    """
    if not chain:
        raise TranscriptUnavailable("there is nothing before that point to copy")
    new_session = new_session or str(uuid_module.uuid4())
    source_session = index.source_session_id or index.path.stem
    try:
        dest_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = dest_dir / f"{new_session}.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise TranscriptUnavailable(f"the copy could not be created: {exc.strerror or exc}") from exc
    try:
        with os.fdopen(fd, "wb") as out, index.path.open("rb") as source:
            if index.suppressed:
                out.write(_line({"type": "history-suppression", "sessionId": new_session, "cause": "fork_inherit",
                                 "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}))
            for line in _messages(source, chain, new_session, source_session):
                out.write(line)
            for line in _carried(source, index, new_session, source_session):
                out.write(line)
            out.flush()
            os.fsync(out.fileno())
        _fsync_dir(dest_dir)
    except (OSError, TranscriptChanged) as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, TranscriptChanged):
            raise
        raise TranscriptUnavailable(f"the copy could not be written: {exc.strerror or exc}") from exc
    logger.info("bookmark_copy_written", source=str(index.path), copy=str(path), records=len(chain),
                conversation=new_session)
    return new_session, path


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        logger.debug("bookmark_dir_fsync_skipped", directory=str(directory), error=str(exc))
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        logger.debug("bookmark_dir_fsync_refused", directory=str(directory), error=str(exc))
    finally:
        os.close(fd)


def remove_copy(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("bookmark_copy_remove_failed", path=str(path), error=str(exc))
