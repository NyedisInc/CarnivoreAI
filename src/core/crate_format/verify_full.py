
from __future__ import annotations

import hashlib
import secrets
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Set

from src.core.blobcodec.chunking import chain_sha
from src.core.crate_format import canonical
from src.core.crate_format.constants import DRILL_SPACE_FACTOR, MAX_ROWS_LINE
from src.core.crate_format.errors import CrateCorrupt, CrateError, CrateMalformed
from src.core.crate_format.extract import extract_all
from src.core.crate_format.model import MemberRecord
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_format.tarsink import content_id_of

if TYPE_CHECKING:
    from src.core.crate_format.verify import VerifyReport


def _members(reader: CrateReader, report: "VerifyReport") -> List[MemberRecord]:
    actual: List[MemberRecord] = []
    for listed in reader.manifest.members:
        if not reader.has(listed.name):
            continue
        digest, size = hashlib.sha256(), 0
        for piece in reader.iter_member(listed.name):
            digest.update(piece)
            size += len(piece)
        record = MemberRecord(listed.name, size, digest.hexdigest())
        actual.append(record)
        report.members_checked += 1
        if record.size != listed.size or record.sha256 != listed.sha256:
            report.add("member_mismatch", listed.name, "size or sha256 differs from crate.json")
    return actual


def _file(reader: CrateReader, record: FileRecord, report: "VerifyReport", bad: Set[str], good: Set[str]) -> None:
    if sum(ref.length for ref in record.chunks) != record.length:
        report.add("content_mismatch", record.place, "the chunk lengths do not sum to the file length")
    if chain_sha(list(record.chunks)) != record.chain_sha256:
        report.add("chain_mismatch", record.place, "the chunk list does not hash to chain_sha256")
    digest, whole = hashlib.sha256(), True
    for ref in record.chunks:
        if ref.sha256 in bad:
            whole = False
            continue
        try:
            digest.update(reader.read_chunk(ref))
            good.add(ref.sha256)
        except CrateCorrupt as exc:
            bad.add(ref.sha256)
            whole = False
            found = reader.blob_member(ref.sha256)
            report.add(exc.code, found[0] if found else f"blobs/{ref.sha256[:2]}/{ref.sha256}", str(exc))
    if whole and digest.hexdigest() != record.content_sha256:
        report.add("content_mismatch", record.place, "the chunks do not hash to content_sha256")
    report.files_checked += 1


def _rows(reader: CrateReader, report: "VerifyReport") -> None:
    for store, tables in reader.tables().items():
        for table, record in tables.items():
            count = 0
            for part in record.parts:
                if not reader.has(part):
                    report.add("rows_mismatch", part, f"table {store}.{table} names a part that is missing")
                    continue
                for line in reader.iter_lines(part, MAX_ROWS_LINE):
                    count += 1
                    try:
                        if not isinstance(canonical.loads(line), dict):
                            raise ValueError("not an object")
                    except ValueError:
                        report.add("rows_mismatch", part, f"line {count} is not a JSON object")
            if count != record.rows:
                report.add("rows_mismatch", f"{store}.{table}", f"{count} lines where schema.json says {record.rows}")


def run(reader: CrateReader, report: "VerifyReport", progress: Optional[Callable[[int], None]] = None) -> None:
    actual = _members(reader, report)
    if content_id_of(actual) != reader.manifest.content_id:
        report.add("content_id_mismatch", None, "the content members do not hash to crate.json's content_id")
    try:
        files = reader.files()
        bad: Set[str] = set()
        good: Set[str] = set()
        referenced: Dict[str, None] = {}
        done = 0
        for record in files:
            _file(reader, record, report, bad, good)
            referenced.update((ref.sha256, None) for ref in record.chunks)
            done += record.length
            if progress is not None:
                progress(done)
        for name in reader.blob_names():
            if name.split("/")[2].split(".")[0] not in referenced:
                report.add("extra_blob", name, "no file references this blob")
        report.blobs_checked = len(good)
        _rows(reader, report)
    except CrateMalformed as exc:
        report.add("malformed", None, str(exc))


def drill(reader: CrateReader, report: "VerifyReport", scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    need = int(sum(r.length for r in reader.files()) * DRILL_SPACE_FACTOR)
    if shutil.disk_usage(scratch).free < need:
        report.add("no_space", None, f"a drill needs {need} free bytes under its scratch folder")
        return
    folder = scratch / f"drill-{secrets.token_hex(6)}"
    try:
        extract_all(reader, folder)
    except CrateError as exc:
        report.add(exc.code, None, str(exc))
    except OSError as exc:
        report.add("malformed", None, f"the drill could not extract a file: {exc.strerror or type(exc).__name__}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
