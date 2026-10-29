
from __future__ import annotations

import dataclasses
import hashlib
import re
import secrets
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from src.cplugs.crate import policy as P
from src.cplugs.crate import share as S
from src.cplugs.crate.plan_files import PlannedFile
from src.cplugs.crate.source_read import open_chunks
from src.cplugs.crate.write_files import SkipFile, Transform
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs

ENGINE = "message_model_secrets"
NOTE = ("the detectors find known credential shapes in text; they do not find personal data, client names, other "
        "clients' code, or secrets inside images")
NOT_TEXT = "not UTF-8 text; a share carries text only"
PATH_PLACEHOLDER = "<folder>"
_PROJECTS_ENC = re.compile(r"projects/[^/\s]+/")
_ABSOLUTE = re.compile(r"(?<![\w.\-/])~?/[^\s'\",;()]+")


def place(home: str, rel: str) -> str:
    return str(S.clean_text(S.shared_rel(home, rel), cf.constants.M_FILES))


def _lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    held: List[bytes] = []
    for chunk in chunks:
        if b"\n" not in chunk:
            held.append(chunk)
            continue
        parts = chunk.split(b"\n")
        held.append(parts[0])
        yield b"".join(held) + b"\n"
        for part in parts[1:-1]:
            yield part + b"\n"
        held = [parts[-1]] if parts[-1] else []
    tail = b"".join(held)
    if tail:
        yield tail


def make_transform(stats: S.ShareStats, home: Optional[str] = None) -> Transform:
    def transform(pf: PlannedFile, chunks: Iterator[bytes]) -> Iterator[bytes]:
        member = f"{pf.home}/{pf.home_index}/{cs.redact(S.shared_rel(pf.home, pf.rel))}"
        seen, made = hashlib.sha256(), hashlib.sha256()

        def read() -> Iterator[bytes]:
            for chunk in chunks:
                seen.update(chunk)
                yield chunk

        if pf.line_mode:
            out: Iterator[bytes] = S.transform_lines(_lines(read()), stats, last_may_be_torn=True, member=member, home=home)
        else:
            data = S.transform_text(b"".join(read()), stats, member=member, home=home)
            if data is None:
                raise SkipFile(NOT_TEXT)
            out = iter([data])

        def written() -> Iterator[bytes]:
            for piece in out:
                made.update(piece)
                yield piece

        yield from open_chunks(written(), pf.line_mode)
        if seen.digest() != made.digest():
            stats.files_changed += 1

    return transform


def _store_of(pf_key: str) -> str:
    return pf_key.rsplit("/", 1)[0]


def reconcile_rows(plan: Any, files: Iterable[PlannedFile], written: Dict[str, Tuple[int, int]]) -> List[Dict[str, Any]]:
    store_written: Dict[str, List[int]] = {}
    for artifact, store in sorted({(f.artifact, _store_of(f.key)) for f in files}):
        count, size = written.get(artifact, (0, 0))
        acc = store_written.setdefault(store, [0, 0])
        acc[0], acc[1] = acc[0] + count, acc[1] + size
    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in plan.reconcile:
        key = (row["store"], row["decision"])
        agg = rows.setdefault(key, {"store": row["store"], "kind": "aggregate", "inventory_count": 0, "inventory_size": 0,
                                    "decision": row["decision"], "reason": row["reason"], "written_count": 0,
                                    "written_bytes": 0})
        agg["inventory_count"] += int(row.get("inventory_count") or 0)
        agg["inventory_size"] += int(row.get("inventory_size") or 0)
    out: List[Dict[str, Any]] = []
    for (store, decision), agg in sorted(rows.items()):
        if decision == P.CARRY:
            count, size = store_written.get(store, [0, 0])
            agg.update(written_count=count, written_bytes=size, status="ok")
        else:
            agg["status"] = {P.EXCLUDE: "excluded", P.DERIVED: "derived", "gap": "gap"}.get(decision, decision)
        agg["reason"] = S.clean_text(agg["reason"], cf.constants.M_RECONCILE)
        out.append(agg)
    return out


def conversation_records(plan: Any, harness: Dict[str, Any]) -> List[cf.ConversationRecord]:
    out: List[cf.ConversationRecord] = []
    for conv in plan.conversations:
        codex = conv["family"] == P.HOME_CODEX
        out.append(cf.ConversationRecord(
            id=conv["id"], family=conv["family"], title=S.clean_text(conv["title"], cf.constants.M_MANIFEST),
            session_uuid=conv["session_uuid"], working_dir=None,
            main_rel=place(P.HOME_CODEX if codex else P.HOME_CLAUDE, conv["main_rel"]), enc_folder=None,
            harness_versions=sorted(harness.get(conv["id"], ())),
            resume=cf.constants.RESUME_CODEX if codex else cf.constants.RESUME_FORK_ONLY, origin=conv["origin"],
            orphan=bool(conv["orphan"])))
    return out


def redaction_block(stats: S.ShareStats) -> Dict[str, Any]:
    return {"engine": ENGINE, "detectors": sorted(cs.ALL_DETECTORS), "detectors_sha256": cs.detectors_digest(),
            "findings": dict(sorted(stats.findings.items())), "files_changed": stats.files_changed,
            "images_stripped": stats.images_stripped, "home_scrubbed": stats.home_scrubbed,
            "torn_dropped": stats.torn_dropped, "residual_scan": "clean", "note": NOTE}


def secrets_json(stats: S.ShareStats, digest: str) -> Dict[str, Any]:
    return {"engine": ENGINE, "mode": "redaction", "detectors_sha256": digest, "by_file": {},
            "by_detector": dict(sorted(stats.findings.items())), "total": sum(stats.findings.values())}


def _scope(plan: Any) -> Dict[str, Any]:
    subject = plan.subject
    sessions = sorted(plan.keys.session_uuids)
    if plan.request.scope == cs.SCOPE_PROJECT:
        return {"kind": "project", "project_uid": subject.get("uid"),
                "project_name": S.clean_text(subject.get("name"), cf.constants.M_MANIFEST), "project_root": None,
                "session_uuids": sessions}
    return {"kind": "session", "session_uuid": subject.get("session_uuid"),
            "title": S.clean_text(subject.get("title"), cf.constants.M_MANIFEST), "session_uuids": sessions}


def _known_places(plan: Any) -> List[str]:
    found = {str(f.enc_folder) for f in plan.files if getattr(f, "enc_folder", None)}
    found |= {str(c.get(k)) for c in plan.conversations for k in ("enc_folder", "working_dir") if c.get(k)}
    subject = (plan.subject.get("root"), plan.subject.get("working_dir"), plan.request.target)
    found |= {str(v) for v in subject if v and str(v).startswith(("/", "~"))}
    return sorted(found, key=len, reverse=True)


def share_sentence(text: Optional[str], plan: Any, member: str) -> Optional[str]:
    if text is None:
        return None
    out = _PROJECTS_ENC.sub("projects/_shared/", text)
    for place_name in _known_places(plan):
        out = out.replace(place_name, PATH_PLACEHOLDER)
    return S.clean_text(_ABSOLUTE.sub(PATH_PLACEHOLDER, out), member)


def share_id() -> str:
    return secrets.token_hex(8)


def finish(manifest: cf.CrateManifest, plan: Any, stats: S.ShareStats, skipped: List[Dict[str, Any]]) -> cf.CrateManifest:
    member = cf.constants.M_MANIFEST
    excluded = [{k: v for k, v in e.items() if k != "what"} for e in list(manifest.excluded) + list(skipped)]
    total = sum(stats.findings.values())
    done = dataclasses.replace(
        manifest, label=S.clean_text(manifest.label, member), source={"share_id": share_id()}, scope=_scope(plan),
        homes=[cf.HomeRecord(h.kind, h.index, None) for h in manifest.homes],
        excluded=[dict(e, reason=share_sentence(e.get("reason"), plan, member)) for e in excluded],
        warnings=[str(share_sentence(w, plan, member)) for w in manifest.warnings],
        secrets={"scanned": True, "findings": total, "by_detector": dict(sorted(stats.findings.items()))},
        redaction=redaction_block(stats))
    S.gate_member(member, done.as_json())
    return done
