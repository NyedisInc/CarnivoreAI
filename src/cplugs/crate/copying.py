
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Sequence

from src.cplugs.crate import constants as K
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.publish import NameTaken, publish, write_new
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf


class CopyFailed(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _stream_copy(src: Path, temp: Path, job: JobHandle) -> None:
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, K.FILE_MODE)
    with os.fdopen(fd, "wb") as out, open(src, "rb") as handle:
        for block in iter(lambda: handle.read(bc.READ_BYTES), b""):
            started = time.monotonic()
            job.check()
            out.write(block)
            job.add(len(block))
            job.rest(time.monotonic() - started)
        out.flush()
        os.fsync(out.fileno())


def copy_crate(src: Path, folder: Path, sha256: str, job: JobHandle, *, identities: Sequence[object] = (),
               sidecars: Sequence[tuple] = ()) -> Path:
    final = Path(folder) / src.name
    temp = Path(folder) / f".{src.name}.partial"
    job.temp(str(temp))
    published: List[Path] = []
    try:
        _stream_copy(src, temp, job)
        encrypted = src.name.endswith(".age")
        level = "quick" if encrypted and not identities else "full"
        report = cf.verify(temp, level, expected_sha256=sha256, extra_identities=list(identities))
        if not report.ok:
            raise CopyFailed("verify_failed", ", ".join(report.codes))
        publish(temp, final)
        published.append(final)
        job.untemp(str(temp))
        for name, data in sidecars:
            write_new(Path(folder) / name, data, job.temp)
            published.append(Path(folder) / name)
            job.untemp(str(Path(folder) / f".{name}.partial"))
        return final
    except BaseException as exc:
        for path in published:
            if os.path.lexists(path):
                os.unlink(path)
        if isinstance(exc, NameTaken):
            raise CopyFailed("name_taken", str(exc)) from exc
        if isinstance(exc, OSError):
            raise CopyFailed("copy_failed", f"{type(exc).__name__}: {exc}") from exc
        raise
    finally:
        if temp.exists():
            os.unlink(temp)
            job.untemp(str(temp))

