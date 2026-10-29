
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.blobcodec.codec import CodecUnavailable
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import analysis as an
from src.core.crate_import import backups_folder_in, backups_in, files_place, ledger, share_in
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import B_CODEC_UNAVAILABLE, Finding, ImportRequest

PLAN_VERSION = 1

logger = structlog.get_logger()


def _fingerprint(material: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _sessions_block(a: an.Analysis) -> Dict[str, Any]:
    plan = a.sessions
    return {"reminted": sorted(plan.reminted),
            "attached": sorted([old, new] for old, new in plan.translate.items() if old not in plan.reminted),
            "left_out": sorted(plan.skip_sessions),
            "share": [s.session_uuid for s in share_in.sessions_of(a.manifest, [p.record for p in a.placements])] if share_in.is_share(a.manifest) else []}


def fingerprint_of(a: an.Analysis, conn: Any) -> str:
    assert a.rows is not None
    return _fingerprint({
        "crate": a.crate_sha256, "request": a.request.as_json(), "provenance": [a.prov.kind, a.prov.reason],
        "dest": [[str(p.dest), p.cls, an.lstat_key(p.dest)] for p in a.placements if p.dest is not None],
        "live": [sorted(a.live.live_conversations), sorted(a.live.live_sessions)], "rows": a.rows.rows,
        "project": a.decision.project_json(), "sessions": _sessions_block(a), "plugin_data": a.plugin_data, "side": a.side.view() if a.side else None, "ledger": [e["import_id"] for e in ledger.entries_from(conn, a.source_install or "")],
    })


def build_plan(reader: CrateReader, env: ImportEnv, request: ImportRequest, *, crate_sha256: str, encrypted: bool,
               source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    manifest = reader.manifest
    crate_info = {"bundle_id": manifest.bundle_id, "label": manifest.label, "created_at": manifest.created_at,
                  "variant": manifest.variant, "scope": manifest.scope.get("kind"), "encrypted": encrypted,
                  "format_version": list(manifest.format_version)}
    answer: Dict[str, Any] = {"version": PLAN_VERSION, "source": source or {}, "crate": crate_info}
    conn = env.connect()
    try:
        return {**answer, **render(an.analyze(reader, env, conn, request, crate_sha256), conn)}
    except CodecUnavailable as exc:
        logger.warning("crate_import_codec_unavailable", error=str(exc))
        return {**answer, "ok": False, "fingerprint": "", "provenance": None, "provenance_reason": None, "project": None,
                "mapping": [], "blockers": [Finding(B_CODEC_UNAVAILABLE, str(exc)).as_json()], "warnings": []}
    finally:
        conn.close()


def _project_folder(a: an.Analysis) -> Optional[Dict[str, Any]]:
    root = a.decision.root_to
    if not root:
        return None
    side = a.side.view() if a.side else None
    return {"path": str(root), "create": not os.path.lexists(root), "files": side["placement"] if side else None,
            "side": side["path"] if side and not a.side.into_root else None}


def render(a: an.Analysis, conn: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"provenance": a.prov.kind, "provenance_reason": a.prov.reason, "project": a.decision.project_json(),
                           "mapping": a.decision.mapping_sources, "carries": dict(a.carries), "project_folder": _project_folder(a),
                           "cleanup": dict(a.cleanup), "backups": dict(a.backups)}
    if a.decision.action is None or a.rows is None:
        return {**out, "ok": False, "fingerprint": "", "blockers": [b.as_json() for b in a.col.blockers],
                "warnings": [w.as_json() for w in a.col.warnings]}
    out.update({
        "enc": [e.as_json() for e in a.enc.values()], "conversations": a.conversations, "rows": a.rows.rows, "sessions": _sessions_block(a),
        "rewrites": a.rows.rewrites, "dropped": a.rows.dropped,
        "files": {"restamp": True, "count": sum(a.by_home.values()), "bytes": a.needed, "by_home": a.by_home, "task_files": a.task_files, "side_folder": a.side.view() if a.side else None,
                  "boards_beside": [b["slug"] for v in a.plugin_data for b in v["boards"] if b["outcome"] == "beside"],
                  "conflicts_kept": [p.dest.as_posix() for p in a.placements if p.cls == files_place.CLASS_CONFLICT and p.dest]},
        "entries": a.entries, "plugin_data": a.plugin_data, "journal": {"rebased": a.journal_rebased},
        "trust": {"crate_said": None, "engine": "asks", "folders": []},
        "instructions": _instructions(a.placements), "secrets": {"count_by_kind": dict(a.manifest.secrets.get("by_detector") or {})},
        "not_restored": a.rows.not_restored + files_not_restored(a.placements) + _plugin_not_restored(a.plugin_data) + backups_in.not_restored(a.backups) + backups_folder_in.not_restored(a.backups),
        "space": {"needed": a.needed, "free": a.free, "volume": a.volume},
    })
    out["blockers"] = [b.as_json() for b in a.col.blockers]
    out["warnings"] = [w.as_json() for w in a.col.warnings]
    out["ok"] = not a.col.blockers
    out["fingerprint"] = fingerprint_of(a, conn)
    return out


def _plugin_not_restored(views: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    why = {"not_ticked": "plugin_data_not_ticked", "unlocated": "plugin_store_unlocated"}
    return [{"what": f"plugin_data:{v['store']}", "why": v.get("reason") or why[v["decision"]]} for v in views if v["decision"] in why]


def files_not_restored(placements: List[files_place.Placement]) -> List[Dict[str, str]]:
    seen: Dict[Tuple[str, str], int] = {}
    for p in placements:
        if p.action not in (files_place.ACT_PLACE, files_place.ACT_AFTER_ROWS, files_place.ACT_SIDE_FOLDER):
            seen[(p.record.role, p.reason or p.action)] = seen.get((p.record.role, p.reason or p.action), 0) + 1
    return [{"what": f"files:{role} ({n})", "why": why} for (role, why), n in sorted(seen.items())]


def _instructions(placements: List[files_place.Placement]) -> Dict[str, Any]:
    memory = [p for p in placements if p.record.role in ("memory", "project_note")]
    plans = [p for p in placements if p.record.role == "plan"]
    return {"memory_files": len(memory), "plans": len(plans),
            "held_back": any(p.reason == "instructions_held_back" for p in memory + plans)}
