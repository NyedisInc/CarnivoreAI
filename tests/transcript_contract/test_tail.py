
from __future__ import annotations

import json
from pathlib import Path

from src.core.attention.transcript_facts import read_transcript_facts
from src.core.claude_title_sync import read_tail_records
from src.core.session_status_seed_records import classify_tail_records
from src.core.transcript_contract import UnknownRecord
from src.core.transcript_contract.tail import decode_window

_TS = "2026-09-30T12:00:00.000Z"
_KNOWN = [
    {"type": "user", "timestamp": _TS, "isSidechain": False,
     "message": {"role": "user", "content": "hello"}},
    {"type": "assistant", "timestamp": _TS, "isSidechain": False,
     "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
    {"type": "system", "subtype": "turn_duration", "timestamp": _TS, "version": "2.1.286",
     "pendingBackgroundAgentCount": 0},
]
_UNKNOWN = {"type": "zz-record-from-a-newer-claude", "timestamp": _TS, "payload": {"a": 1}}


def _write(path: Path, records: list) -> str:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


def test_unknown_record_type_is_carried_and_changes_no_status(tmp_path: Path) -> None:
    plain = _write(tmp_path / "plain.jsonl", _KNOWN)
    mixed = _write(tmp_path / "mixed.jsonl", [_KNOWN[0], _UNKNOWN, *_KNOWN[1:], _UNKNOWN])

    read = read_tail_records(mixed)
    assert read.readable and _UNKNOWN in read.records
    typed = [line for line in read.typed() if line.kind == _UNKNOWN["type"]]
    assert len(typed) == 2 and all(isinstance(t.record, UnknownRecord) and not t.known for t in typed)

    assert read_transcript_facts(mixed) == read_transcript_facts(plain)
    assert classify_tail_records(read.records) == classify_tail_records(
        read_tail_records(plain).records)


def test_decode_window_skips_torn_and_non_object_lines() -> None:
    window = b'{"type":"mode"}\n\xff\xfe\n[1,2]\n\n  {"type":"summary"}  \n{"type":"us'
    assert [o["type"] for o in decode_window(window)] == ["mode", "summary"]
    assert [o["type"] for o in decode_window(window, drop_first_line=True)] == ["summary"]
