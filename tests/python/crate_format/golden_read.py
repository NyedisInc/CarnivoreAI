
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from src.core.blobcodec.codec import decompress
from src.core.crate_crypto import keys
from src.core.crate_format import constants as C, names
from src.core.crate_format.model import MAP_FIELDS, OPAQUE_FIELDS
from src.core.crate_format.reader import CrateReader, open_crate

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "crate"
V1 = FIXTURES_ROOT / "v1"
KEY_SEED = b"carnivore crate golden v1 test key, not a secret"
SHAPED_MEMBERS = (C.M_MANIFEST, C.M_FILES, C.M_SCHEMA, C.M_ENTRIES, C.M_RECONCILE, C.M_SECRETS)
WRITER_KINDS = (names.KIND_FIXED, names.KIND_ROWS, names.KIND_LINES, names.KIND_BLOB)
ENCODINGS = ("$b64", "$t64", "$f")
CODEC_OF_SUFFIX = {"zst": "zstd", "xz": "lzma"}


def test_identity(seed: bytes = KEY_SEED) -> str:
    return keys.encode_identity(hashlib.sha256(seed).digest())


test_identity.__test__ = False


def test_recipient(seed: bytes = KEY_SEED) -> str:
    return keys.recipient_of(test_identity(seed))


test_recipient.__test__ = False


def identity_for(path: Path) -> Optional[str]:
    return test_identity() if path.name.endswith(".age") else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(C.READ_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def listing(path: Path) -> Dict[str, Any]:
    with open_crate(path, identity_for(path)) as reader:
        m = reader.manifest
        return {
            "bundle_sha256": sha256_file(path), "content_id": m.content_id, "format_version": list(m.format_version),
            "variant": m.variant, "conversations": sorted(c.id for c in m.conversations),
            "files": sorted(({"home": f.home, "home_index": f.home_index, "rel": f.rel, "length": f.length,
                              "content_sha256": f.content_sha256} for f in reader.files()),
                            key=lambda r: (r["home"], r["home_index"], r["rel"])),
            "rows": {store: {name: t.rows for name, t in sorted(tables.items())}
                     for store, tables in sorted(reader.tables().items())},
            "members": sorted(x.name for x in reader.members()),
            "blobs": {"count": m.blobs["count"], "set_sha256": m.blobs["set_sha256"]},
        }


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    for kind, name in ((bool, "bool"), (int, "int"), (float, "float"), (str, "str"), (list, "list"), (dict, "dict")):
        if isinstance(value, kind):
            return name
    return type(value).__name__


def _walk(value: Any, path: str, dotted: str, maps: Set[str], opaque: Set[str], out: Set[str]) -> None:
    out.add(f"{path or '$'} {_type_name(value)}")
    if dotted in opaque:
        return
    if isinstance(value, dict):
        as_map = dotted in maps
        for key, inner in value.items():
            step = "*" if as_map else key
            _walk(inner, f"{path}.{step}" if path else step, f"{dotted}.{step}" if dotted else step, maps, opaque, out)
    elif isinstance(value, list):
        for inner in value:
            _walk(inner, f"{path}[]", f"{dotted}[]", maps, opaque, out)


def key_shape(member: str, values: Iterable[Any]) -> List[str]:
    out: Set[str] = set()
    for value in values:
        _walk(value, "", "", set(MAP_FIELDS.get(member, ())), set(OPAQUE_FIELDS.get(member, ())), out)
    return sorted(out)


def _member_values(reader: CrateReader, name: str) -> List[Any]:
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in reader.iter_lines(name) if line.strip()]
    return [reader.read_json(name)]


ADDED_AFTER_V1: Dict[str, Tuple[str, ...]] = {"crate.json": ("scope.project_uid ", "scope.project_name ", "scope.project_root ")}


def shapes(path: Path) -> Dict[str, List[str]]:
    with open_crate(path, identity_for(path)) as reader:
        out = {name: [line for line in key_shape(name, _member_values(reader, name)) if not line.startswith(ADDED_AFTER_V1.get(name, ()))]
               for name in SHAPED_MEMBERS if reader.has(name)}
        out["member_kinds"] = sorted({str(names.member_kind(x.name)) for x in reader.members()})
    return out


def _encodings(value: Any, found: Set[str]) -> None:
    if isinstance(value, dict):
        if len(value) == 1 and next(iter(value)) in ENCODINGS:
            found.add(next(iter(value)))
        for inner in value.values():
            _encodings(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _encodings(inner, found)


def coverage(paths: Sequence[Path]) -> Dict[str, List[str]]:
    seen: Dict[str, Set[str]] = {axis: set() for axis in
                                 ("roles", "homes", "member_kinds", "encodings", "entry_stores", "lines_sources",
                                  "codecs", "variants")}
    for path in paths:
        with open_crate(path, identity_for(path)) as reader:
            seen["variants"].add(reader.manifest.variant)
            for record in reader.files():
                seen["roles"].add(record.role)
                seen["homes"].add(record.home)
            for member in reader.members():
                seen["member_kinds"].add(str(names.member_kind(member.name)))
                if member.name.startswith(C.BLOBS_PREFIX):
                    seen["codecs"].add(CODEC_OF_SUFFIX[member.name.rsplit(".", 1)[-1]])
                if member.name.startswith(C.LINES_PREFIX):
                    seen["lines_sources"].add(member.name[len(C.LINES_PREFIX):].rsplit("-", 1)[0])
            seen["entry_stores"].update(e["store"] for e in reader.read_json(C.M_ENTRIES)["entries"])
            for tables in reader.tables().values():
                for table in tables.values():
                    for part in table.parts:
                        for line in reader.iter_lines(part):
                            _encodings(json.loads(line), seen["encodings"])
    return {axis: sorted(values) for axis, values in seen.items()}


def member_texts(path: Path) -> Iterator[Tuple[str, bytes]]:
    with open_crate(path, identity_for(path)) as reader:
        for member in reader.members():
            raw = reader.read_member(member.name)
            if member.name.startswith(C.BLOBS_PREFIX):
                found = reader.blob_member(member.name.split("/")[-1].split(".")[0])
                raw = decompress(raw, found[1]) if found else raw
            yield member.name, raw


def identity_hits(paths: Sequence[Path], needles: Sequence[str]) -> List[Tuple[str, str, str]]:
    wanted = [(n, n.encode("utf-8")) for n in needles if n]
    hits = []
    for path in paths:
        texts = member_texts(path) if path.name.endswith((".crate", ".crate.age")) else [("-", path.read_bytes())]
        for member, data in texts:
            hits += [(path.name, member, text) for text, raw in wanted if raw in data]
    return hits
