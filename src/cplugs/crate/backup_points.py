
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.plan_files import ORIGIN_VAULT, PlannedFile
from src.cplugs.crate.vault_files import VaultWalk, home_of_plugin
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.core.deepsearch import fallback_hook as fb

KIND_CONVERSATION = "conversation"
DATA_ID = cf.constants.BACKUPS_DATA
PROVIDES = cf.constants.PROVIDES_BACKUP_POINTS
POINT_FILE = "point.json"
FORMAT = 1
_KEY = f"{cs.STORE_VAULT}/*"


def point_meta(point: fb.FallbackPoint, scope_by: str = "") -> Dict[str, Any]:
    folder = {"kind": point.kind, "scope_by": scope_by} if point.kind != KIND_CONVERSATION else {}
    return {**folder, "v": FORMAT, "conversation_id": point.conversation_id, "point_id": point.point_id, "reason": point.reason,
            "created_epoch": point.created_epoch, "created_at": point.created_at, "family": point.family,
            "session_uuid": point.session_uuid, "project_uid": point.project_uid, "project_name": point.project_name,
            "working_dir": point.working_dir, "encoded_folder": point.encoded_folder, "wrapper": point.wrapper, "title": point.title,
            "files": [{"n": n, "role": f.role, "home": f.home, "rel": f.rel, "source_path": f.source_path, "length": f.length,
                       "mode": f.mode, "mtime_ns": f.mtime_ns, "lines": f.lines} for n, f in enumerate(point.files)]}


def _planned(provider: str, conversation: str, point: fb.FallbackPoint, rel: str, size: int, **extra: Any) -> PlannedFile:
    unit = conversation if point.kind != KIND_CONVERSATION else ""
    return PlannedFile(key=_KEY, role=P.R_PLUGIN_FILE, home=home_of_plugin(provider), home_index=0, rel=rel, source_path=None,
                       conversation_id=None, family=None, enc_folder=None, size=size, plugin=provider, data=DATA_ID,
                       provides=PROVIDES, artifact=f"backups:{conversation}", backup_unit=unit, **extra)


def plan_point(provider: str, conversation: str, point: fb.FallbackPoint, scope_by: str = "") -> List[PlannedFile]:
    """The planned files of one point: ``point.json`` (bytes in hand) and every file (read from the vault when written).

    Inputs: provider (the plugin id that provides backup points); conversation (the conversation id, or a folder point's unit);
    scope_by (a folder point's store scope, written into ``point.json``). Raises: cf.UnsafeName (a conversation or point id a crate
    cannot name). Pure."""
    base = f"{DATA_ID}/{conversation}/{point.point_id}"
    cf.check_rel(f"{base}/{POINT_FILE}")
    meta = json.dumps(point_meta(point, scope_by), sort_keys=True, separators=(",", ":")).encode("utf-8")
    out = [_planned(provider, conversation, point, f"{base}/{POINT_FILE}", len(meta), line_mode=False, inline=meta)]
    for n, f in enumerate(point.files):
        out.append(_planned(provider, conversation, point, f"{base}/files/{n}", f.length, line_mode=f.role in cf.constants.LINE_ROLES,
                            origin=ORIGIN_VAULT, vault=(f"{point.point_id}:{f.sha256}:{f.length}", f.rel),
                            vault_conversation=conversation, vault_point=point.point_id))
    return out


def _carry_all(walk: VaultWalk, provider: str, conversation: str, points: Sequence[fb.FallbackPoint]) -> None:
    files: List[PlannedFile] = []
    for point in points:
        try:
            files += plan_point(provider, conversation, point)
        except cf.UnsafeName as exc:
            walk.warnings.append(f"backup_point_skipped: {point.point_id} of conversation {conversation} has a name a crate cannot carry ({exc})")
    if not files:
        return
    walk.files += files
    walk.reconcile.append({"store": cs.STORE_VAULT, "kind": cs.KIND_FILE, "inventory_count": len(files),
                           "inventory_size": sum(f.size for f in files), "decision": P.CARRY, "what": f"backups:{conversation}",
                           "reason": "every backup point of the conversation (include_backups)"})


def plan_backups(scope_ids: Sequence[str], provider: Optional[str], sources: Optional[Sequence[Any]] = None) -> VaultWalk:
    walk = VaultWalk()
    chosen = [s for s in (cs.fallback_sources() if sources is None else sources) if hasattr(s, "list_points")]
    if provider is None or not chosen:
        walk.blockers.append((K.B_BACKUPS_OFF, "include backups is ticked and the conversation backup plugin is off"))
        return walk
    for conversation in sorted(scope_ids):
        for source in chosen:
            try:
                points = source.list_points(conversation)
            except OSError as exc:
                walk.blockers.append((K.B_VAULT, f"the backup of conversation {conversation} cannot be reached ({type(exc).__name__})"))
                break
            except fb.FallbackUnavailable as exc:
                walk.blockers.append((K.B_VAULT_INCOMPLETE, f"the backup points of conversation {conversation} cannot be read ({exc})"))
                break
            if points:
                _carry_all(walk, provider, conversation, points)
                break
    return walk
