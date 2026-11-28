
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.agy import transcripts as agy
from src.core.pack.migrate import transcripts
from src.core.pack.migrate.plan import MigrateError
from src.core.pack.migrate.receive import MigrateRefused


def allowed(conversation_id: Optional[str]) -> Callable[[str], bool]:
    if not agy.valid_id(conversation_id):
        return lambda rel: False
    brain, store = f"brain/{conversation_id}/", f"conversations/{conversation_id}.db"
    return lambda rel: rel == store or (rel.startswith(brain) and len(rel) > len(brain) and ".." not in Path(rel).parts)


def source_files(conversation_id: str, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    files = agy.carry_files(conversation_id, home)
    rels = {f["rel"] for f in files}
    if f"conversations/{conversation_id}.db" not in rels or not any(r.endswith("/.system_generated/logs/transcript.jsonl") for r in rels):
        raise MigrateError("no_conversation_file", "this computer holds no agy transcript and store for the session's conversation, so it could not resume elsewhere", 409)
    if sum(f["size"] for f in files) > transcripts.MAX_TRANSCRIPT_BYTES:
        raise MigrateError("too_large", "the agy conversation's files are too large to carry", 409)
    for entry in files:
        entry["sha256"] = transcripts._sha256(Path(entry["path"]))
    return files


def file_conversation(archive: str, files: List[Dict[str, Any]], conversation_id: Optional[str], home: Optional[Path] = None) -> None:
    base = Path(home or agy.AGY_HOME)
    check = allowed(conversation_id)
    for sub in ("brain", "conversations"):
        if (base / sub).is_symlink():
            raise MigrateRefused("unsafe_archive", f"agy's {sub} folder here is a link, so nothing is written into it")
    if any(not check(str(f.get("rel"))) for f in files):
        raise MigrateRefused("unsafe_archive", "the conversation files name a path outside the one conversation")
    try:
        _written, _same, replaced = transcripts.unpack_into(archive, base, check)
    except transcripts.TranscriptError as exc:
        raise MigrateRefused(exc.code, exc.detail) from exc
    misses = transcripts.verify_in(files, base)
    if misses:
        raise MigrateRefused("verify_failed", "the conversation did not arrive intact: " + ", ".join(misses[:5]))
    transcripts.drop_backups(base, replaced)
