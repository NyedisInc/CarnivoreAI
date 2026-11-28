
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import structlog

from src.core.deepsearch import fallback_hook as fb
from src.core.json_artifact import atomic_write_json
from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest import store
from src.core.transcript_manifest.scan import Row

logger = structlog.get_logger(__name__)

RECORD_FILE: str = "transcripts-gone-uncovered.json"
MAX_IDS: int = 2000
MAX_LOGGED: int = 50
SAMPLES: int = 5
RECHECK_SECONDS: float = 600.0


def read_record(state_dir: Path) -> Dict[str, object]:
    try:
        data = json.loads((Path(state_dir) / RECORD_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("transcript_gone_record_unreadable", error=str(exc), error_type=type(exc).__name__)
        return {}
    return data if isinstance(data, dict) else {}


def held_by_vault(conversation_id: str, *, ask_while_booting: bool = False) -> Optional[bool]:
    found = fb.sources()
    if not found or (fb.booting() and not ask_while_booting):
        return None
    unknown = False
    for source in found:
        try:
            if source.files(conversation_id):
                return True
        except (fb.FallbackUnavailable, OSError) as exc:
            logger.warning("transcript_gone_vault_unreadable", conversation_id=conversation_id, error=str(exc)[:200])
            unknown = True
    return None if unknown else False


def _ids(record: Dict[str, object], key: str) -> List[str]:
    value = record.get(key)
    return [str(i) for i in value] if isinstance(value, list) else []


def _number(record: Dict[str, object], key: str) -> int:
    value = record.get(key)
    return int(value) if isinstance(value, int) and value > 0 else 0


def _write(state_dir: Path, record: Dict[str, object]) -> None:
    path = Path(state_dir) / RECORD_FILE
    if not record["count"] and not record["pending"] and not record["pending_overflow"]:
        path.unlink(missing_ok=True)
        return
    if not atomic_write_json(path, record, log_event="transcript_gone_record_write_failed"):
        logger.error("transcript_gone_record_unwritable", path=str(path), count=record["count"])


def _vault_state() -> str:
    if fb.booting():
        return "wait"
    return "ask" if fb.sources() else "none"


class _Sorted:

    def __init__(self) -> None:
        self.uncovered: List[str] = []
        self.pending: List[str] = []


def _classify(conn: sqlite3.Connection, record_ids: List[str], pending_ids: List[str], fresh: Dict[str, Row],
              state: str, due: bool) -> _Sorted:
    out = _Sorted()
    known = set(record_ids)
    waiting = set(pending_ids)
    for conversation_id in dict.fromkeys([*record_ids, *pending_ids, *fresh]):
        if store.path_for_conversation(conn, conversation_id, None) is not None:
            continue
        was_recorded = conversation_id in known
        if state == "none":
            if was_recorded:
                out.uncovered.append(conversation_id)
            elif conversation_id in waiting:
                out.pending.append(conversation_id)
            continue
        if state == "wait" or (was_recorded and not due):
            (out.uncovered if was_recorded else out.pending).append(conversation_id)
            continue
        held = held_by_vault(conversation_id)
        if held is False or (held is None and was_recorded):
            out.uncovered.append(conversation_id)
        elif held is None:
            out.pending.append(conversation_id)
    return out


def _log_new(newly: List[str], fresh: Dict[str, Row], total: int) -> None:
    for conversation_id in newly[:MAX_LOGGED]:
        row = fresh.get(conversation_id)
        logger.error("transcript_gone_without_vault_copy", conversation_id=conversation_id,
                     path=row.path if row else "", family=row.family if row else "",
                     note="the original is gone and the vault holds no copy of this conversation")
    if len(newly) > MAX_LOGGED:
        logger.error("transcript_gone_without_vault_copy_more", more=len(newly) - MAX_LOGGED, total=total)


def audit(state_dir: Path, conn: sqlite3.Connection, removed: Sequence[Row], now: Optional[float] = None) -> None:
    stamp = time.time() if now is None else now
    prior = read_record(state_dir)
    record_ids, pending_ids = _ids(prior, "ids"), _ids(prior, "pending")
    fresh: Dict[str, Row] = {r.conversation_id: r for r in removed if r.kind == K.KIND_CONVERSATION and r.conversation_id}
    if not fresh and not record_ids and not pending_ids:
        return
    last = prior.get("rechecked_at")
    due = not isinstance(last, (int, float)) or stamp - last >= RECHECK_SECONDS
    state = _vault_state()
    try:
        sorted_ids = _classify(conn, record_ids, pending_ids, fresh, state, due)
        newly = [c for c in sorted_ids.uncovered if c not in set(record_ids)]
        _log_new(newly, fresh, len(sorted_ids.uncovered))
        overflow = _number(prior, "overflow") + max(0, len(sorted_ids.uncovered) - MAX_IDS)
        pending_overflow = _number(prior, "pending_overflow") + max(0, len(sorted_ids.pending) - MAX_IDS)
        if pending_overflow > _number(prior, "pending_overflow"):
            logger.error("transcript_gone_pending_overflow", pending_overflow=pending_overflow,
                         note="removals the vault could not answer for are past the record's cap and will not be asked again")
        ids = sorted_ids.uncovered[:MAX_IDS]
        _write(state_dir, {"at": stamp, "count": len(ids) + overflow, "ids": ids, "samples": ids[:SAMPLES], "overflow": overflow,
                           "pending": sorted_ids.pending[:MAX_IDS], "pending_overflow": pending_overflow,
                           "rechecked_at": stamp if state == "ask" and due else last if isinstance(last, (int, float)) else stamp})
    except (sqlite3.Error, OSError) as exc:
        logger.error("transcript_gone_audit_failed", error=str(exc), error_type=type(exc).__name__)
