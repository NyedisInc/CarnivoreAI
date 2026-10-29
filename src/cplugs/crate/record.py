
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.cplugs.crate.env import CrateEnv
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import exports as sx

LEVEL_QUICK = "quick"


def published_record(*, bundle_id: str, path: str, sha256: str, size: int, scope: str, variant: str,
                     created_epoch: int, label: Optional[str], project_uid: Optional[str], session_uuid: Optional[str],
                     conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"bundle_id": bundle_id, "path": path, "sha256": sha256, "size": size, "scope": scope, "variant": variant,
            "created_epoch": int(created_epoch), "label": label, "project_uid": project_uid,
            "session_uuid": session_uuid,
            "conversations": [{"id": c["id"], "family": c["family"], "title": c.get("title")} for c in conversations]}


def record_published(env: CrateEnv, rec: Mapping[str, Any], at: float, *, written: bool = False) -> sx.Bundle:
    bundle = sx.Bundle(bundle_id=str(rec["bundle_id"]), sha256=str(rec["sha256"]), scope=str(rec["scope"]),
                       created_at=float(rec["created_epoch"]), project_uid=rec.get("project_uid"),
                       session_uuid=rec.get("session_uuid"), label=rec.get("label"),
                       locations=(sx.Location(str(rec["path"]), at),), verified_at=at)
    created = float(rec["created_epoch"])
    pointers = [sx.Pointer(c["id"], c["family"], bundle.bundle_id, created, c.get("title")) for c in rec["conversations"]]
    return sx.with_main_db(lambda conn: sx.record_bundle(conn, bundle, pointers, written_mark=bundle.sha256 if written else None),
                           state=env.state)


def record_own(env: CrateEnv, plan: Any, result: Any, at: float) -> sx.Bundle:
    return record_published(env, writer_record(plan, result.bundle_id, str(result.path), result.sha256, result.size,
                                               int(result.created_epoch)), at, written=True)


def writer_record(plan: Any, bundle_id: str, path: str, sha256: str, size: int, created_epoch: int) -> Dict[str, Any]:
    subject = plan.subject
    return published_record(bundle_id=bundle_id, path=path, sha256=sha256, size=size, scope=plan.request.scope,
                            variant=plan.request.variant, created_epoch=created_epoch, label=plan.request.label,
                            project_uid=subject.get("uid"), session_uuid=subject.get("session_uuid"),
                            conversations=plan.conversations)


def manifest_record(manifest: cf.CrateManifest, path: Path, sha256: str, size: int) -> Dict[str, Any]:
    scope = manifest.scope or {}
    return published_record(bundle_id=manifest.bundle_id, path=str(path), sha256=sha256, size=size,
                            scope=str(scope.get("kind")), variant=manifest.variant,
                            created_epoch=int(manifest.created_epoch), label=manifest.label,
                            project_uid=scope.get("project_uid"), session_uuid=scope.get("session_uuid"),
                            conversations=[{"id": c.id, "family": c.family, "title": c.title}
                                           for c in manifest.conversations])


def add_location(env: CrateEnv, bundle_id: str, where: str, verified_at: Optional[float]) -> sx.Bundle:
    def work(conn: Any) -> sx.Bundle:
        found = sx.bundle(conn, bundle_id)
        kept = [loc for loc in found.locations if loc.where != where]
        return sx.update_bundle(conn, bundle_id, locations=kept + [sx.Location(where, verified_at)])

    return sx.with_main_db(work, state=env.state)


def mark_verified(env: CrateEnv, bundle_id: str, where: str, level: str, at: float) -> sx.Bundle:
    def work(conn: Any) -> sx.Bundle:
        found = sx.bundle(conn, bundle_id)
        locations: List[sx.Location] = [replace(loc, verified_at=at) if loc.where == where else loc
                                        for loc in found.locations]
        return sx.update_bundle(conn, bundle_id, locations=locations,
                                verified_at=None if level == LEVEL_QUICK else at)

    return sx.with_main_db(work, state=env.state)


def mark_removed(env: CrateEnv, bundle_id: str) -> sx.Bundle:
    return sx.with_main_db(lambda conn: sx.update_bundle(conn, bundle_id, local_removed=True), state=env.state)
