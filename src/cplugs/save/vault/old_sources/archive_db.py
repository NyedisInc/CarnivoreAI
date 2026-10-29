
from __future__ import annotations

import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.parse import quote

import structlog

from src.cplugs.save.vault.old_sources import model, names

logger = structlog.get_logger()

SOURCE_PREFIX = "archive:"
_COLUMNS = "id, source_path, content_sha256, raw_byte_length, ingested_at"


def _epoch(stamp: Optional[str]) -> float:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _opener(db: Path, row_id: int) -> Callable[[], Iterator[bytes]]:
    def open_bytes() -> Iterator[bytes]:
        con = sqlite3.connect(_uri(db), uri=True)
        try:
            row = con.execute("SELECT content_gzip FROM transcript_archives WHERE id=?", (row_id,)).fetchone()
        finally:
            con.close()
        if row is None:
            raise FileNotFoundError(f"row {row_id}")
        inflater = zlib.decompressobj()
        blob = bytes(row[0])
        for start in range(0, len(blob), model.READ_BLOCK):
            out = inflater.decompress(blob[start:start + model.READ_BLOCK])
            if out:
                yield out
        tail = inflater.flush()
        if tail:
            yield tail
    return open_bytes


def _uri(db: Path) -> str:
    return f"file:{quote(str(db))}?mode=ro&immutable=1"


def iter_copies(db: Path, intake: model.Intake, name: Optional[str] = None, *, newest_only: bool = True, trust: bool = False) -> Iterator[model.Copy]:
    """Every transcript row of the archive database ``db`` as a verified :class:`model.Copy`, in row order. Blocking.

    Inputs: db; intake (collects refused and skipped rows); name (the source name, default ``archive:<file stem>``); newest_only;
    trust (a preview takes each row's recorded sha256 and length without inflating it, see ``model.checked``).
    Raises: model.SourceError (the database cannot be opened or has no transcript table).
    Example: [c.ident.conv for c in iter_copies(Path('final-cloude-archive.db'), model.Intake())][:1]
    """
    source = name or SOURCE_PREFIX + Path(db).stem
    try:
        con = sqlite3.connect(_uri(Path(db)), uri=True)
        rows = con.execute(f"SELECT {_COLUMNS} FROM transcript_archives" + (" WHERE superseded_by_archive_id IS NULL" if newest_only else "")
                           ).fetchall()
        rows.sort(key=lambda r: r[0])
        con.close()
    except sqlite3.Error as exc:
        raise model.SourceError(f"{db}: {type(exc).__name__}: {exc}") from exc
    for row_id, path, sha, length, ingested in rows:
        locator = f"db:{Path(db).name}:{row_id}"
        ident = names.identify(str(path))
        if ident is None or names.is_appledouble(str(path)):
            intake.skipped.append(model.Refusal(source, locator, "not a transcript path" if ident is None else "appledouble"))
            continue
        copy = model.checked(intake, source, locator, ident, _opener(Path(db), row_id), _epoch(ingested),
                             want_sha=sha, want_length=length, errors=(OSError, zlib.error, sqlite3.Error), trust=trust)
        if copy is not None:
            yield copy
