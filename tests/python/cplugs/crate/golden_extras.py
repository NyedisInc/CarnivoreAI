
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Dict

from src.core.claude_transcript_correlate import slugify_project_dir
from tests.python.cplugs.crate.export_extras import add_extras
from tests.python.inventory.world import CONV_A, CONV_A0, CONV_B, CONV_D

SECRET_VALUE = "golden-wait-token-hash-never-carried"
EMPTY_TABLE = "swarm_suggestions"
BLOB_VALUE = bytes([0, 255, 16, 32])
NOT_UTF8 = bytes([0xFF, 0xFE, 0x41])
REAL_VALUE = 0.25
PARTS_PATH_NAME = "golden-spec.md"
IMAGE_DATA = "iVBORw0KGgo="


def placeholder_token() -> str:
    return "ghp_" + "x" * 36


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _sql(db: Path, statement: str, *params: object) -> None:
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(statement, params)
        conn.commit()


def _share_lines(home: str) -> bytes:
    records = [
        {"type": "user", "sessionId": CONV_B, "message": {"role": "user", "content": f"use {placeholder_token()} now"}},
        {"type": "user", "sessionId": CONV_B, "message": {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": IMAGE_DATA}}]}},
        {"type": "assistant", "sessionId": CONV_B, "message": {"role": "assistant", "content": f"read {home}/notes.md"}},
    ]
    return b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in records)


def _seed_files(w: SimpleNamespace, paths: Dict[str, Path], home: str) -> None:
    projects = Path(w.home) / "projects"
    enc1 = slugify_project_dir(w.root1)
    line = json.dumps({"type": "user", "message": {"content": "an older copy"}}).encode() + b"\n"
    paths["set_aside"] = _write(projects / enc1 / f"{CONV_A}.jsonl.from-old-key-1", line)
    paths["conflict"] = _write(projects / enc1 / f"{CONV_A} 2.jsonl", line)
    paths["archived"] = _write(projects / "_hold-for-archive" / enc1 / f"{CONV_A0}.jsonl", line)
    paths["notes"] = _write(projects / enc1 / "sessions-index.json", b'{"entries": []}\n')
    history = b"".join(json.dumps({"display": text, "project": w.root1, "sessionId": conv}).encode() + b"\n"
                       for text, conv in (("hello", CONV_A), ("decoy", CONV_D)))
    paths["history"] = _write(Path(w.home) / "history.jsonl", history)
    transcript = projects / enc1 / f"{CONV_B}.jsonl"
    paths["share_lines"] = _write(transcript, transcript.read_bytes() + _share_lines(home))


def _seed_rows(w: SimpleNamespace) -> None:
    runs = Path(w.side["automations.db"])
    _sql(runs, "UPDATE runs SET report = ?, error = CAST(? AS TEXT), cost_usd = ?, slot_at = 9e999, notes = NULL",
         BLOB_VALUE, NOT_UTF8, REAL_VALUE)
    huddle = Path(w.state) / "carnivore.db"
    _sql(huddle, "UPDATE work_item_waits SET token_hash = ?", SECRET_VALUE)
    parts = json.dumps({"files": [{"path": str(Path(w.root1) / PARTS_PATH_NAME)}]})
    _sql(huddle, "UPDATE work_messages SET parts = ? WHERE item_id = ?", parts, w.item_a)
    _sql(Path(w.state) / "carnivore.db", f"DELETE FROM {EMPTY_TABLE}")


def add_golden_extras(w: SimpleNamespace, home: str) -> Dict[str, Path]:
    paths = add_extras(w)
    _seed_files(w, paths, home)
    _seed_rows(w)
    return paths
