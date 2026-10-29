
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.core.crate_format.backup_files import is_backup_point_file
from src.core.crate_format.constants import BACKUPS_DATA
from src.core.crate_format.errors import CrateError
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import.env import ImportEnv
from src.core.deepsearch import fallback_hook as fb

logger = structlog.get_logger()

POINT_FILE = "point.json"
KIND_FOLDER = "folder"
MAX_POINT_JSON_BYTES = 8 * 1024 * 1024
ST_RESTORE, ST_PRESENT, ST_NOT_RESTORED = "restore", "present", "not_restored"
R_PLUGIN_OFF, R_NOT_CHOSEN, R_EXCLUDED, R_INCOMPLETE = "backup_plugin_off", "backups_not_chosen", "conversation_left_out", "point_incomplete"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,199}$")
_PROJECTS = re.compile(r"^projects/([^/]+)/(.+)$")


@dataclass
class Point:

    conversation: str
    point_id: str
    meta: Dict[str, Any]
    records: Dict[int, FileRecord] = field(default_factory=dict)

    @property
    def is_folder(self) -> bool:
        return self.meta.get("kind") == KIND_FOLDER

    @property
    def bytes(self) -> int:
        return sum(r.length for r in self.records.values())


def _own_record(r: FileRecord) -> bool:
    return is_backup_point_file(r.role, r.home, r.rel, r.extra)


def carried(reader: CrateReader, files: Sequence[FileRecord], *, folders: bool = False) -> Dict[str, List[Point]]:
    by_rel = {r.rel: r for r in files if _own_record(r)}
    out: Dict[str, List[Point]] = {}
    for rel, record in sorted(by_rel.items()):
        parts = rel.split("/")
        if len(parts) != 4 or parts[3] != POINT_FILE or not _ID.match(parts[1]) or record.length > MAX_POINT_JSON_BYTES:
            continue
        conversation, point_id = parts[1], parts[2]
        try:
            meta = json.loads(b"".join(reader.file_chunks(record)))
        except (ValueError, CrateError):
            continue
        if not isinstance(meta, dict) or meta.get("conversation_id") != conversation or meta.get("point_id") != point_id:
            continue
        listed = meta.get("files")
        if not isinstance(listed, list) or not listed:
            continue
        point = Point(conversation, point_id, meta)
        if point.is_folder != folders:
            continue
        for item in listed:
            n = item.get("n") if isinstance(item, dict) else None
            found = by_rel.get(f"{BACKUPS_DATA}/{conversation}/{point_id}/files/{n}") if isinstance(n, int) else None
            if found is None or found.length != item.get("length"):
                break
            point.records[n] = found
        else:
            out.setdefault(conversation, []).append(point)
    return out


def adopter(env: ImportEnv) -> Optional[Any]:
    return next((s for s in env.backup_sources() if hasattr(s, "adopt_points")), None)


def _already(source: Any, conversation: str, points: Sequence[Point]) -> int:
    try:
        held = {p.point_id for p in source.list_points(conversation)}
    except (OSError, fb.FallbackUnavailable):
        return 0
    return sum(1 for p in points if p.point_id in held)


def plan_view(found: Dict[str, List[Point]], env: ImportEnv, *, filing: bool, excluded: Sequence[str]) -> Dict[str, Any]:
    provider = adopter(env)
    source = provider if filing else None
    rows: List[Dict[str, Any]] = []
    for conversation, points in sorted(found.items()):
        reason = R_NOT_CHOSEN if not filing else (R_EXCLUDED if conversation in excluded else (R_PLUGIN_OFF if source is None else None))
        already = _already(source, conversation, points) if reason is None else 0
        status = ST_NOT_RESTORED if reason else (ST_PRESENT if already == len(points) else ST_RESTORE)
        rows.append({"id": conversation, "points": len(points), "files": sum(len(p.records) for p in points),
                     "bytes": sum(p.bytes for p in points), "already": already, "status": status, "reason": reason})
    return {"carried": bool(rows), "restores": any(r["status"] == ST_RESTORE for r in rows), "provider_enabled": provider is not None,
            "conversations": rows}


def not_restored(view: Dict[str, Any]) -> List[Dict[str, str]]:
    return [{"what": f"backups:{r['id']}", "why": r["reason"]} for r in view.get("conversations", []) if r["status"] == ST_NOT_RESTORED]


def _remap_rel(home: str, rel: str, enc: Dict[str, Any]) -> str:
    found = _PROJECTS.match(rel) if home == "claude" else None
    if found is None or found.group(1) not in enc:
        return rel
    return f"projects/{enc[found.group(1)].target}/{found.group(2)}"


def _incoming(reader: CrateReader, point: Point, env: ImportEnv, enc: Dict[str, Any], mapping: Any, sessions: Sequence[str]) -> fb.FallbackPoint:
    meta = point.meta
    home_of = {"claude": Path(env.claude_homes[0]), "codex": Path(env.codex_home)}
    files = []
    for item in meta["files"]:
        record = point.records[item["n"]]
        rel = _remap_rel(item["home"], str(item["rel"]), enc)
        files.append(fb.IncomingFile(
            role=str(item["role"]), home=str(item["home"]), rel=rel, source_path=str(home_of.get(item["home"], Path("/")) / rel),
            length=int(item["length"]), sha256=record.content_sha256, mode=int(item.get("mode") or 0), mtime_ns=int(item.get("mtime_ns") or 0),
            lines=int(item.get("lines") or 0), read=lambda r=record: reader.file_chunks(r)))
    working = meta.get("working_dir")
    folder = meta.get("encoded_folder")
    return fb.FallbackPoint(
        conversation_id=point.conversation, point_id=point.point_id, reason=str(meta.get("reason") or "import"),
        created_epoch=float(meta.get("created_epoch") or 0), created_at=str(meta.get("created_at") or ""), family=str(meta.get("family") or "claude"),
        files=tuple(files), session_uuid=meta.get("session_uuid") if meta.get("session_uuid") in sessions else None,
        project_uid=meta.get("project_uid"), project_name=meta.get("project_name"),
        working_dir=mapping.apply(working) if working else None, encoded_folder=enc[folder].target if folder in enc else folder,
        wrapper=meta.get("wrapper"), title=meta.get("title"))


def incoming_points(reader: CrateReader, found: Dict[str, List[Point]], env: ImportEnv, enc: Dict[str, Any], mapping: Any,
                    sessions: Sequence[str], excluded: Sequence[str]) -> List[fb.FallbackPoint]:
    return [_incoming(reader, p, env, enc, mapping, sessions) for c, points in sorted(found.items()) if c not in excluded for p in points
            if not p.is_folder]


def present_total(view_rows: Sequence[Dict[str, Any]], results: Sequence[fb.AdoptedPoint]) -> int:
    answered = {r.conversation_id for r in results}
    return sum(1 for r in results if r.status == "present") + sum(
        int(row.get("points") or 0) for row in view_rows if row.get("status") == ST_PRESENT and row.get("id") not in answered)


def receipt_block(view: Dict[str, Any], results: Sequence[fb.AdoptedPoint]) -> Dict[str, Any]:
    return {"adopted": sum(1 for r in results if r.status == "adopted"), "present": present_total(view.get("conversations", []), results),
            "refused": [{"conversation": r.conversation_id, "point": r.source_point_id, "reason": r.reason} for r in results if r.status == "refused"],
            "not_restored": not_restored(view)}
