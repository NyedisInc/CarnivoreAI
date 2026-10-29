
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.core.blobcodec.codec import BLOB_EXTENSIONS
from src.core.crate_format import verify_full
from src.core.crate_format.constants import AGE_MAGIC, M_MAGIC, M_MANIFEST, READ_BYTES
from src.core.crate_format.errors import CrateError
from src.core.crate_format.reader import CrateReader, Identity, open_crate
from src.core.crate_format.tarsink import blob_set_sha256

LEVEL_QUICK, LEVEL_FULL, LEVEL_DRILL = "quick", "full", "drill"
LEVELS: Tuple[str, ...] = (LEVEL_QUICK, LEVEL_FULL, LEVEL_DRILL)
PROBLEM_CODES: Tuple[str, ...] = (
    "sha_mismatch", "no_expected_hash", "malformed", "too_new", "missing_member", "extra_member", "member_mismatch",
    "blob_corrupt", "missing_blob", "extra_blob", "chain_mismatch", "content_mismatch", "rows_mismatch",
    "content_id_mismatch", "needs_identity", "wrong_key", "age_corrupt", "no_space",
)
# could not
COULD_NOT_CHECK: Tuple[str, ...] = ("no_expected_hash", "too_new", "needs_identity", "wrong_key", "no_space")


@dataclass
class VerifyReport:

    ok: bool
    level: str
    encrypted: bool
    bundle_sha256: str
    content_id: Optional[str] = None
    format_version: Optional[Tuple[int, int]] = None
    members_checked: int = 0
    blobs_checked: int = 0
    files_checked: int = 0
    bytes: int = 0
    problems: List[Dict[str, Optional[str]]] = field(default_factory=list)

    def add(self, code: str, member: Optional[str] = None, detail: str = "") -> None:
        self.problems.append({"code": code, "member": member, "detail": detail})
        self.ok = False

    @property
    def codes(self) -> List[str]:
        return [p["code"] for p in self.problems]

    def as_json(self) -> Dict[str, Any]:
        out = asdict(self)
        out["format_version"] = list(self.format_version) if self.format_version else None
        return out


def _file_sha(path: Path, progress: Optional[Callable[[int], None]]) -> Tuple[str, int, bool]:
    digest, size, head = hashlib.sha256(), 0, b""
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(READ_BYTES), b""):
            if size == 0:
                head = block[:len(AGE_MAGIC)]
            digest.update(block)
            size += len(block)
            if progress is not None:
                progress(size)
    return digest.hexdigest(), size, head == AGE_MAGIC


def _age_layout(path: Path, size: int, report: VerifyReport) -> None:
    from src.core.crate_crypto.age import NONCE_BYTES, SEALED_CHUNK_BYTES, TAG_BYTES
    from src.core.crate_crypto.age_header import MAX_HEADER_BYTES, parse_header
    from src.core.crate_crypto.errors import Malformed

    with open(path, "rb") as handle:
        try:
            header = parse_header(handle.read(MAX_HEADER_BYTES))
        except Malformed as exc:
            report.add("malformed", None, f"age header: {exc}")
            return
    sealed = size - header.length - NONCE_BYTES
    last = sealed % SEALED_CHUNK_BYTES or (SEALED_CHUNK_BYTES if sealed else 0)
    if sealed < TAG_BYTES or last < TAG_BYTES or (sealed > SEALED_CHUNK_BYTES and last == TAG_BYTES):
        report.add("age_corrupt", None, "the age payload length does not fit the chunk layout")


def _member_set(reader: CrateReader, report: VerifyReport) -> None:
    listed = {m.name for m in reader.manifest.members}
    present = {m.name for m in reader.members() if m.kind != "blob"} - {M_MAGIC, M_MANIFEST}
    for name in sorted(listed - present):
        report.add("missing_member", name, "listed in crate.json but not in the container")
    for name in sorted(present - listed):
        report.add("extra_member", name, "in the container but not listed in crate.json")
    blobs, want = reader.blob_names(), reader.manifest.blobs
    if len(blobs) < want["count"]:
        report.add("missing_blob", None, f"{want['count'] - len(blobs)} fewer blobs than crate.json counts")
    elif len(blobs) > want["count"]:
        report.add("extra_blob", None, f"{len(blobs) - want['count']} more blobs than crate.json counts")
    elif blob_set_sha256(blobs) != want["set_sha256"]:
        report.add("member_mismatch", "blobs", "the blob names do not hash to crate.json's set_sha256")
    codec_of = {ext: codec for codec, ext in BLOB_EXTENSIONS.items()}
    used = {codec_of.get("." + name.rsplit(".", 1)[-1]) for name in blobs}
    if used != {str(c) for c in want.get("codecs") or []}:
        report.add("member_mismatch", "blobs", "the blob codecs differ from crate.json's blobs.codecs")


def verify(path: Path, level: str = LEVEL_FULL, expected_sha256: Optional[str] = None,
           identity: Optional[Identity] = None, extra_identities: Sequence[Identity] = (),
           progress: Optional[Callable[[int], None]] = None, scratch: Optional[Path] = None) -> VerifyReport:
    if level not in LEVELS:
        raise ValueError(f"unknown verify level {level!r}")
    if level == LEVEL_DRILL and scratch is None:
        raise ValueError("a drill needs a scratch folder")
    sha, size, encrypted = _file_sha(Path(path), progress)
    report = VerifyReport(ok=True, level=level, encrypted=encrypted, bundle_sha256=sha, bytes=size)
    if expected_sha256 is None:
        report.add("no_expected_hash", None, "no expected sha256 was given or found")
    elif expected_sha256.strip().lower() != sha:
        report.add("sha_mismatch", None, "the file's sha256 differs from the expected one")
    identities = ([identity] if identity is not None else []) + list(extra_identities)
    if encrypted and not identities:
        _age_layout(Path(path), size, report)
        if level != LEVEL_QUICK:
            report.add("needs_identity", None, "an age identity is needed above quick")
        return report
    try:
        reader = open_crate(Path(path), identity, extra_identities=extra_identities)
    except CrateError as exc:
        report.add(exc.code, None, str(exc))
        return report
    with reader:
        report.format_version = reader.format_version
        report.content_id = reader.manifest.content_id
        _member_set(reader, report)
        if level != LEVEL_QUICK:
            verify_full.run(reader, report, progress)
        if level == LEVEL_DRILL and report.ok:
            verify_full.drill(reader, report, Path(scratch))
    return report


def expected_from_sidecar(path: Path) -> Optional[str]:
    side = Path(f"{path}.sha256")
    try:
        first = side.read_text(encoding="ascii").split()
    except (OSError, UnicodeDecodeError):
        return None
    return first[0].lower() if first and len(first[0]) == 64 else None

