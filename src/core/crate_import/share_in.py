"""
A share crate carries no rows, no entries and no install id (``docs/crate.md``, section 6): redacted conversation files under a
``_shared`` folder, a project name and uid, and one conversation record per conversation. So an import of one is small and has fixed
rules:

A second import of the same share finds the derived session uuids already here and writes nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import structlog

from src.core.crate_import import fork_marker
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_format.constants import VARIANT_SHARE
from src.core.crate_format.model import ConversationRecord, CrateManifest
from src.core.crate_format.model_files import FileRecord
from src.core.crate_import import idmap
from src.core.crate_import import rows_write as rw
from src.core.crate_import.enc import EncEntry
from src.core.crate_import.session_plan import reminted_uuid
from src.core.crate_import.validate import UUID_RE
from src.core.transcript_import_plan import IMPORTED_ROW_CONSTANTS

logger = structlog.get_logger()

SHARED_FOLDER = "_shared"
VERIFIED_SHARE = "share_target"
CLAUDE_FAMILY = "claude"


@dataclass(frozen=True)
class ShareSession:
    """One session a share crate brings: ``session_uuid`` (the new one), ``conversation`` (its newest Claude conversation id),
    ``title`` and ``sender_uuid`` (the uuid the crate named, or None)."""

    session_uuid: str
    conversation: str
    title: Optional[str]
    sender_uuid: Optional[str]


def is_share(manifest: CrateManifest) -> bool:
    return manifest.variant == VARIANT_SHARE


def enc_for(root: str) -> Dict[str, EncEntry]:
    return {SHARED_FOLDER: EncEntry(SHARED_FOLDER, slugify_project_dir(root), VERIFIED_SHARE, root)}


def _newest(conversations: List[ConversationRecord], files: Iterable[FileRecord]) -> ConversationRecord:
    stamp = {f.conversation_id: f.mtime_ns or 0 for f in files if f.role == "transcript" and f.conversation_id}
    return max(conversations, key=lambda c: (stamp.get(c.id, 0), c.id))


def sessions_of(manifest: CrateManifest, files: Iterable[FileRecord]) -> List[ShareSession]:
    records = list(files)
    groups: Dict[str, List[ConversationRecord]] = {}
    for conv in manifest.conversations:
        if conv.family == CLAUDE_FAMILY and not conv.orphan and UUID_RE.match(conv.id):
            groups.setdefault(conv.session_uuid or conv.id, []).append(conv)
    out = []
    for key, convs in groups.items():
        newest = _newest(convs, records)
        out.append(ShareSession(reminted_uuid(manifest.bundle_id, key), newest.id, newest.title, key if convs[0].session_uuid else None))
    return sorted(out, key=lambda s: s.session_uuid)


def bad_identifiers(manifest: CrateManifest) -> List[str]:
    return sorted({c.id for c in manifest.conversations if c.family == CLAUDE_FAMILY and not c.orphan and not UUID_RE.match(c.id)})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_sessions(ctx: rw.WriteCtx, manifest: CrateManifest, files: Iterable[FileRecord], project_id: int, working_dir: str) -> None:
    counts = ctx.table_counts(idmap.SESSIONS)
    now = _now()
    for share in sessions_of(manifest, files):
        if ctx.conn.execute("SELECT 1 FROM sessions WHERE session_uuid = ?", (share.session_uuid,)).fetchone() is not None:
            counts.present += 1
            continue
        row = {**IMPORTED_ROW_CONSTANTS, "session_uuid": share.session_uuid, "project_id": project_id, "working_dir": working_dir,
               "agent_type": CLAUDE_FAMILY, "claude_session_uuid": share.conversation, "title": share.title,
               "created_at": now, "updated_at": now}
        try:
            _inserted, rowid = rw.insert_row(ctx, "sessions", rw.own_columns(ctx, "sessions", row), ignore=False)
        except sqlite3.IntegrityError as exc:  # conversation id
            logger.warning("crate_import_share_session_refused", error=str(exc)[:120])
            counts.skip("refused_by_unique_rule")
            continue
        counts.inserted += 1
        ctx.created.setdefault(idmap.SESSIONS, []).append(rowid)
        fork_marker.set_marker(ctx.conn, share.session_uuid, share.conversation)
