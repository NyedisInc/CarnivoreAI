
from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.core.blobcodec.chunking import ChunkReader, chain_sha
from src.core.crate_format import canonical
from src.core.crate_format.canonical import RawText
from src.core.crate_format.constants import (
    FORMAT, LINE_ROLES, M_ENTRIES, M_EXTRACT, M_FILES, M_MAGIC, M_MANIFEST, M_PATHS, M_README, M_RECONCILE, M_SCHEMA,
    M_SECRETS, MAGIC,
)
from src.core.crate_format.tarsink import CrateSink, content_id_of, template_bytes

EPOCH = 1792267200
CONV = "11111111-2222-4333-8444-555555555555"
CODEX_CONV = "019a0000-0000-7000-8000-00000000c0de"
ENC = "-Users-x-app"
WORKING_DIR = "/Users/x/app"


@dataclass
class SrcFile:

    role: str
    home: str
    rel: str
    data: bytes
    conversation_id: Optional[str] = None
    family: Optional[str] = "claude"
    home_index: int = 0
    mode: int = 0o600
    mtime_ns: Optional[int] = 1792267000 * 10**9
    extra: Dict[str, Any] = field(default_factory=dict)


def transcript(lines: int = 3) -> bytes:
    out = b""
    for i in range(lines):
        out += canonical.dumps({"type": "user" if i % 2 == 0 else "assistant", "uuid": f"u{i}", "sessionId": CONV,
                                "cwd": WORKING_DIR, "version": "2.1.283", "message": {"text": f"turn {i}"}})
    return out


def default_files() -> List[SrcFile]:
    base = f"projects/{ENC}/{CONV}"
    return [
        SrcFile("transcript", "claude", f"{base}.jsonl", transcript(), CONV),
        SrcFile("subagent", "claude", f"{base}/subagents/agent-1.jsonl", transcript(2), CONV),
        SrcFile("tool_result", "claude", f"{base}/tool-results/résumé-ü.txt", "unicode body é\n".encode(), CONV),
        SrcFile("conversation_file", "claude", f"{base}/notes.txt", b"no trailing newline", CONV),
        SrcFile("file_history", "claude", f"file-history/{CONV}/abc@v1", bytes(range(256)) * 40, CONV, mode=0o644),
        SrcFile("todo", "claude", f"todos/{CONV}-agent-{CONV}.json", b"[]\n", CONV),
        SrcFile("codex_rollout", "codex", f"sessions/2026/10/17/rollout-x-{CODEX_CONV}.jsonl", b'{"a":1}\n',
                CODEX_CONV, family="codex"),
        SrcFile("task_file", "state", "tasks/board.json", b'{"t":1}\n', None, family=None),
    ]


def default_tables() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    return {
        "carnivore.db": {"sessions": [
            {"id": 1, "name": "a", "ratio": 0.5, "note": None, "data": b"\x00\xff", "big": math.inf},
            {"id": 2, "name": RawText(b"\xff\xfe bad"), "ratio": -math.inf, "note": "x", "data": None, "big": 1},
        ]},
        "huddle.db": {"messages": [{"id": 7, "text": "hi"}], "empty_table": []},
    }


def conversations() -> List[Dict[str, Any]]:
    return [
        {"id": CONV, "family": "claude", "title": "test", "session_uuid": "s-uuid", "working_dir": WORKING_DIR,
         "main_rel": f"projects/{ENC}/{CONV}.jsonl", "enc_folder": ENC, "harness_versions": ["2.1.283"],
         "resume": "claude_resume", "origin": "disk"},
        {"id": CODEX_CONV, "family": "codex", "title": None, "session_uuid": None, "working_dir": WORKING_DIR,
         "main_rel": f"sessions/2026/10/17/rollout-x-{CODEX_CONV}.jsonl", "enc_folder": None, "harness_versions": [],
         "resume": "unsupported_codex", "origin": "disk"},
    ]


def _file_record(sink: CrateSink, src: SrcFile, target: Optional[int]) -> Dict[str, Any]:
    line_mode = src.role in LINE_ROLES
    reader = ChunkReader(io.BytesIO(src.data), len(src.data), line_mode, target, keep_tail=True)
    refs = [sink.add_blob(chunk) for chunk in reader]
    record = {"role": src.role, "home": src.home, "home_index": src.home_index, "rel": src.rel,
              "source_path": f"/src/{src.home}/{src.rel}", "conversation_id": src.conversation_id,
              "family": src.family, "enc_folder": ENC if src.rel.startswith("projects/") else None,
              "length": len(src.data), "content_sha256": hashlib.sha256(src.data).hexdigest(),
              "chain_sha256": chain_sha(refs), "chunks": [[r.sha256, r.length] for r in refs], "line_mode": line_mode,
              "lines": src.data.count(b"\n") if line_mode else None, "ends_with_newline": src.data.endswith(b"\n"),
              "mode": src.mode, "mtime_ns": src.mtime_ns, "origin": "disk", "vault_signature": None,
              "redactions": None}
    record.update(src.extra)
    return record


def _rows(sink: CrateSink, tables: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> Dict[str, Any]:
    stores: Dict[str, Any] = {}
    for store, by_name in sorted(tables.items()):
        out_tables = {}
        for table, rows in sorted(by_name.items()):
            parts = []
            if rows:
                name = f"rows/{store}/{table}.jsonl"
                body = b"".join(canonical.jsonl({k: canonical.encode_value(v) for k, v in r.items()} for r in rows))
                sink.add_member(name, body)
                parts.append(name)
            columns = [[c, "", 1 if i == 0 else 0] for i, c in enumerate(rows[0])] if rows else []
            out_tables[table] = {"columns": columns, "rows": len(rows), "parts": parts, "omitted_columns": [],
                                 "without_rowid": False, "keys": ["id"] if rows else [], "paths": []}
        stores[store] = {"inventory_label": "cloude.db" if store == "carnivore.db" else store, "schema_version": 93,
                         "tables": out_tables}
    return {"stores": stores}


def build_crate(path: Path, *, files: Optional[Sequence[SrcFile]] = None,
                tables: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = None,
                convs: Optional[List[Dict[str, Any]]] = None, variant: str = "own", codec: str = "zstd",
                recipients: Sequence[str] = (), minor: int = 0, extra_manifest: Optional[Dict[str, Any]] = None,
                target: Optional[int] = None,
                lines: bool = True) -> Path:
    files = default_files() if files is None else list(files)
    tables = default_tables() if tables is None else tables
    with open(path, "wb") as out:
        writer = None
        raw: Any = out
        if recipients:
            from src.core.crate_crypto.age import AgeWriter
            from src.core.crate_crypto.keys import parse_recipient
            writer = AgeWriter(out, [parse_recipient(r) for r in recipients])
            raw = writer
        sink = CrateSink(raw, EPOCH, codec)
        sink.add_member(M_MAGIC, MAGIC)
        sink.add_member(M_README, template_bytes(M_README))
        sink.add_member(M_EXTRACT, template_bytes(M_EXTRACT))
        schema = _rows(sink, tables)
        if tables:
            sink.add_member(M_SCHEMA, canonical.dumps(schema))
        sink.add_member(M_ENTRIES, canonical.dumps({"entries": []}))
        if lines:
            sink.add_member("lines/claude-history-0.jsonl", b'{"display":"x","sessionId":"%s"}\n' % CONV.encode())
        records = sorted((_file_record(sink, f, target) for f in files),
                         key=lambda r: (r["home"], r["home_index"], r["rel"]))
        sink.add_member(M_FILES, b"".join(canonical.jsonl(records)))
        sink.add_member(M_PATHS, b"")
        sink.add_member(M_SECRETS, canonical.dumps({"engine": "message_model_secrets", "mode": "redaction",
                                                    "detectors_sha256": "0" * 64, "by_file": {}, "total": 0}))
        sink.add_member(M_RECONCILE, canonical.dumps({"artifacts": []}))
        manifest = manifest_json(sink.manifest_members(), sink.blobs_block(), files, variant, minor,
                                 conversations() if convs is None else convs)
        manifest.update(extra_manifest or {})
        sink.add_member(M_MANIFEST, canonical.dumps(manifest))
        sink.close()
        if writer is not None:
            writer.close()
    return path


def manifest_json(members, blobs: Dict[str, Any], files: Sequence[SrcFile], variant: str, minor: int,
                  convs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "format": FORMAT, "format_version": [1, minor], "variant": variant, "byte_exact": variant == "own",
        "resume": "native" if variant == "own" else "fork_only", "complete": True,
        "bundle_id": "crate-20261017T200000Z-session-1a2b3c4d", "label": None, "created_at": "2026-10-17T20:00:00Z",
        "created_epoch": EPOCH, "writer": {"app_version": "test", "codec": "zstd"}, "source": {"install_id": "i"},
        "scope": {"kind": "session"},
        "homes": [{"kind": "claude", "index": 0, "path": None if variant == "share" else "/Users/x/.claude"}],
        "conversations": convs, "members": [m.as_json() for m in members], "blobs": blobs,
        "content_id": content_id_of(members),
        "counts": {"files": len(files), "bytes": sum(len(f.data) for f in files), "rows": {}, "entries": 0,
                   "lines": 1},
        "excluded": [], "warnings": [], "secrets": {"scanned": True, "findings": 0, "by_detector": {}},
        "redaction": None if variant == "own" else {"engine": "test"},
    }
