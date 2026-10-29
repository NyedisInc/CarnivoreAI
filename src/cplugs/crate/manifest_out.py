
from __future__ import annotations

import platform
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.cplugs.crate import policy as P
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs


def files_jsonl(records: Iterable[cf.FileRecord]) -> bytes:
    return b"".join(cf.canonical.dumps(r.as_json()) for r in sorted(records, key=lambda r: r.sort_key))


def paths_jsonl(rows: Sequence[Dict[str, Any]], entries: Sequence[Dict[str, Any]]) -> bytes:
    records = list(rows)
    for entry in entries:
        if entry["store"] == cs.CLAUDE_JSON_STORE and entry["key"].startswith("projects."):
            records.append({"store": entry["store"], "file_index": entry["file_index"], "key": entry["key"],
                            "value": entry["key"][len("projects."):]})
    lines = sorted(cf.canonical.dumps(r) for r in records)
    return b"".join(lines)


def secrets_json(findings: Dict[str, Dict[str, int]], digest: str) -> Dict[str, Any]:
    total = sum(n for per in findings.values() for n in per.values())
    return {"engine": "message_model_secrets", "mode": "redaction", "detectors_sha256": digest,
            "by_file": {k: dict(sorted(v.items())) for k, v in sorted(findings.items())}, "total": total}


def by_detector(findings: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for per in findings.values():
        for detector, n in per.items():
            out[detector] = out.get(detector, 0) + n
    return dict(sorted(out.items()))


def reconcile_rows(plan: Any, written: Dict[str, Any], row_counts: Dict[Any, int], entry_counts: Dict[str, int],
                   line_counts: Dict[str, int], discovered: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in plan.reconcile:
        decision = row["decision"]
        status = {P.EXCLUDE: "excluded", P.DERIVED: "derived", "gap": "gap"}.get(decision, "ok")
        entry = dict(row, written_count=0, written_bytes=0, status=status)
        if decision != P.CARRY:
            out.append(entry)
        elif row["kind"] in (cs.KIND_FILE, cs.KIND_DIR):
            count, size = written.get(row.get("what", ""), (0, 0))
            out.append(dict(entry, written_count=count, written_bytes=size))
        elif row["kind"] == cs.KIND_ENTRY:
            out.append(dict(entry, written_count=entry_counts.get(row["store"], 0)))
        elif row["kind"] == cs.KIND_LINES:
            out.append(dict(entry, written_count=line_counts.get(row.get("what", ""), 0)))
    for (label, table), planned in sorted(plan.row_counts.items()):
        got = row_counts.get((label, table), 0)
        out.append({"store": label, "kind": cs.KIND_ROWS, "what": table, "inventory_count": planned, "inventory_size": 0,
                    "decision": P.CARRY, "reason": "every claimed row, secret columns left out", "written_count": got,
                    "written_bytes": 0, "status": "ok" if got == planned else "changed"})
    return out + list(discovered)


def writer_block(codec: str, app_version: str) -> Dict[str, Any]:
    block: Dict[str, Any] = {"app_version": app_version, "codec": codec, "codec_library": bc.codec_library(),
                             "python": platform.python_version()}
    block["zstd_level" if codec == bc.CODEC_ZSTD else "lzma_preset"] = bc.ZSTD_LEVEL if codec == bc.CODEC_ZSTD else bc.LZMA_PRESET
    return block


def scope_block(plan: Any) -> Dict[str, Any]:
    subject = plan.subject
    sessions = sorted(plan.keys.session_uuids)
    if plan.request.scope == cs.SCOPE_PROJECT:
        return {"kind": "project", "project_uid": subject.get("uid"), "project_name": subject.get("name"),
                "project_root": subject.get("root"), "session_uuids": sessions}
    home = plan.home_project or {}
    out = {"kind": "session", "session_uuid": subject.get("session_uuid"), "title": subject.get("title"), "session_uuids": sessions}
    if home.get("uid"):
        out.update(project_uid=home.get("uid"), project_name=home.get("name"), project_root=home.get("root"))
    return out


def plugin_homes(files: Sequence[Any], own: bool) -> List[Dict[str, Any]]:
    roots: Dict[str, Dict[str, str]] = {}
    for f in files:
        if f.plugin:
            roots.setdefault(f.plugin, {})[f.data] = f.plugin_root
    return [{"kind": f"{P.HOME_PLUGIN_PREFIX}{plugin}", "index": 0, "path": None, "plugin": plugin,
             **({"stores": dict(sorted(stores.items()))} if own else {})} for plugin, stores in sorted(roots.items())]


def homes_block(homes: P.HomesView, project_root: Optional[str] = None, plugin: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    out = [{"kind": P.HOME_CLAUDE, "index": i, "path": h} for i, h in enumerate(homes.claude)]
    out += [{"kind": P.HOME_CODEX, "index": 0, "path": homes.codex}, {"kind": P.HOME_STATE, "index": 0, "path": homes.state}]
    return out + ([{"kind": P.HOME_PROJECT, "index": 0, "path": project_root}] if project_root else []) + list(plugin)


def conversation_records(plan: Any, harness: Dict[str, Any]) -> List[cf.ConversationRecord]:
    out: List[cf.ConversationRecord] = []
    for conv in plan.conversations:
        resume = cf.constants.RESUME_CODEX if conv["family"] == P.HOME_CODEX else cf.constants.RESUME_CLAUDE
        out.append(cf.ConversationRecord(
            id=conv["id"], family=conv["family"], title=conv["title"], session_uuid=conv["session_uuid"],
            working_dir=conv["working_dir"], main_rel=conv["main_rel"], enc_folder=conv["enc_folder"],
            harness_versions=sorted(harness.get(conv["id"], ())), resume=resume, origin=conv["origin"],
            orphan=bool(conv["orphan"])))
    return out


def manifest(*, plan: Any, bundle_id: str, created_epoch: int, created_at: str, writer: Dict[str, Any],
             source: Dict[str, Any], conversations: List[cf.ConversationRecord], members: List[cf.MemberRecord],
             blobs: Dict[str, Any], counts: Dict[str, Any], warnings: List[str], findings: Dict[str, Dict[str, int]],
             redaction: Optional[Dict[str, Any]] = None, extra: Optional[Dict[str, Any]] = None) -> cf.CrateManifest:
    share = plan.request.variant == P.SHARE
    minor = cf.constants.FORMAT_MINOR if plan.v1_1 else cf.constants.FORMAT_MINOR_BASE
    total = sum(n for per in findings.values() for n in per.values())
    return cf.CrateManifest(
        format=cf.constants.FORMAT, format_version=(cf.constants.FORMAT_MAJOR, minor),
        variant=plan.request.variant, byte_exact=not share, resume="fork_only" if share else "native", complete=True,
        bundle_id=bundle_id, label=plan.request.label, created_at=created_at, created_epoch=created_epoch, writer=writer,
        source=source, scope=scope_block(plan), homes=[cf.HomeRecord.from_json(h) for h in homes_block(plan.homes, plan.project_root, plugin_homes(plan.files, not share))],
        conversations=conversations, members=members, blobs=blobs, content_id=cf.content_id_of(members), counts=counts,
        excluded=list(plan.excluded), warnings=list(warnings),
        secrets={"scanned": not share, "findings": total, "by_detector": by_detector(findings)}, redaction=redaction,
        extra=dict(extra or {}))

