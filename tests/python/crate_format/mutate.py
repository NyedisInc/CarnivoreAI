
from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.blobcodec.codec import blob_relpath, compress
from src.core.crate_format import canonical
from src.core.crate_format.model import MemberRecord
from src.core.crate_format.tarsink import blob_set_sha256, content_id_of

Pair = List[Any]


def entries(path: Path) -> List[Pair]:
    out = []
    with tarfile.open(path, "r:") as tar:
        for info in tar:
            out.append([info, tar.extractfile(info).read() if info.isreg() else b""])
    return out


def info(name: str, size: int = 0, kind: bytes = tarfile.REGTYPE, linkname: str = "") -> tarfile.TarInfo:
    item = tarfile.TarInfo(name)
    item.size, item.mode, item.mtime, item.type, item.linkname = size, 0o644, 1792267200, kind, linkname
    return item


def write(pairs: List[Pair], dst: Path) -> Path:
    with tarfile.open(dst, "w", format=tarfile.PAX_FORMAT) as tar:
        for item, data in pairs:
            if item.type == tarfile.REGTYPE:
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
            else:
                tar.addfile(item)
    return dst


def find(pairs: List[Pair], name: str) -> Pair:
    for pair in pairs:
        if pair[0].name == name or (name == "blob" and pair[0].name.startswith("blobs/")):
            return pair
    raise KeyError(name)


def manifest(pairs: List[Pair]) -> Dict[str, Any]:
    return canonical.loads(find(pairs, "crate.json")[1])


def set_manifest(pairs: List[Pair], obj: Dict[str, Any]) -> None:
    find(pairs, "crate.json")[1] = canonical.dumps(obj)


def reseal(pairs: List[Pair]) -> None:
    obj = manifest(pairs)
    members = sorted((MemberRecord(i.name, len(d), hashlib.sha256(d).hexdigest()) for i, d in pairs
                      if not i.name.startswith("blobs/") and i.name not in ("CRATE", "crate.json")),
                     key=lambda m: m.name)
    blobs = [i.name for i, _ in pairs if i.name.startswith("blobs/")]
    obj["members"] = [m.as_json() for m in members]
    obj["blobs"] = {"count": len(blobs), "set_sha256": blob_set_sha256(blobs),
                    "codecs": sorted({"zstd" if b.endswith(".zst") else "lzma" for b in blobs})}
    obj["content_id"] = content_id_of(members)
    set_manifest(pairs, obj)


def edit_files(pairs: List[Pair], fn: Callable[[List[Dict[str, Any]]], None]) -> None:
    pair = find(pairs, "files.jsonl")
    records = [canonical.loads(line) for line in pair[1].splitlines()]
    fn(records)
    pair[1] = b"".join(canonical.jsonl(records))
    reseal(pairs)


def flip(data: bytes, at: Optional[int] = None) -> bytes:
    pos = len(data) // 2 if at is None else at
    return data[:pos] + bytes([data[pos] ^ 0xFF]) + data[pos + 1:]


def insert_before_manifest(pairs: List[Pair], item: tarfile.TarInfo, data: bytes = b"") -> None:
    pairs.insert(len(pairs) - 1, [item, data])


def mutate(src: Path, dst: Path, op: str, **kw: Any) -> Path:
    if op == "truncate":
        data = Path(src).read_bytes()
        Path(dst).write_bytes(data[:kw["at"]])
        return Path(dst)
    pairs = entries(src)
    if op == "flip_blob":
        pair = find(pairs, "blob")
        pair[1] = flip(pair[1])
    elif op == "flip_member":
        pair = find(pairs, kw["name"])
        pair[1] = flip(pair[1])
    elif op == "drop":
        pairs.remove(find(pairs, kw["name"]))
    elif op == "add_unlisted":
        insert_before_manifest(pairs, info(kw["name"]), kw["data"])
    elif op == "orphan_blob":
        raw = os.urandom(64)
        sha = hashlib.sha256(raw).hexdigest()
        insert_before_manifest(pairs, info(blob_relpath(sha, "zstd")), compress(raw, "zstd"))
    elif op == "version":
        obj = manifest(pairs)
        obj["format_version"] = [kw["major"], kw["minor"]]
        set_manifest(pairs, obj)
        reseal(pairs)
    else:
        raise ValueError(op)
    return write(pairs, dst)
