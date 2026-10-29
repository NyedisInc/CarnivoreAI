
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import extracts, folders, record, refs, service
from src.cplugs.crate.copying import copy_crate
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import CrateApiError, conflict, invalid, not_found
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.jobs.runner import JobFailed
from src.cplugs.crate.refs import CrateRef
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk import exports as sx
from src.cplugs.sdk.transcript_files import slugify_project_dir

_SIDECARS = (".sha256", ".README.txt")


def db_guard(exc: Exception) -> CrateApiError:
    return CrateApiError(503, "exports_unavailable", f"the export records could not be read ({type(exc).__name__})")


def known_bundles(env: CrateEnv) -> List[sx.Bundle]:
    try:
        return refs.all_bundles(env)
    except (sx.MainDbUnreadable, sqlite3.Error) as exc:
        raise db_guard(exc) from exc


def resolve(env: CrateEnv, ref: CrateRef, location: Optional[int] = None) -> refs.Resolved:
    try:
        return refs.resolve_ref(env, ref, location)
    except (sx.MainDbUnreadable, sqlite3.Error) as exc:
        raise db_guard(exc) from exc


def _project_keys(env: CrateEnv, project_id: int) -> Tuple[str, frozenset]:
    try:
        keys = cs.project_keys(project_id, state_dir=env.state)
    except cs.SourceUnavailable as exc:
        raise db_guard(exc) from exc
    if keys is None:
        raise not_found("project_not_found", f"no project {project_id}")
    return keys


def _covers(b: sx.Bundle, keys: Optional[Tuple[str, frozenset]]) -> bool:
    if keys is None:
        return True
    uid, sessions = keys
    return (bool(uid) and b.project_uid == uid) or (b.session_uuid is not None and b.session_uuid in sessions)


def _bundle_row(b: sx.Bundle) -> Dict[str, Any]:
    ready = refs.reachable(b)
    return {**refs.bundle_view(b), "project_root": refs.project_root_of(ready[0][1]) if ready else None}


async def bundles(ctx: Any, project: Optional[int] = None) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        keys = _project_keys(env, project) if project is not None else None
        return {"bundles": [_bundle_row(b) for b in known_bundles(env) if _covers(b, keys)]}

    return await asyncio.to_thread(work)


def _plain_summary(path: Path) -> Optional[Dict[str, Any]]:
    if path.name.endswith(".age"):
        return None
    try:
        with cf.open_crate(path) as reader:
            return refs.manifest_summary(reader.manifest)
    except (OSError, cf.CrateError):
        return None


async def bundle(ctx: Any, bundle_id: str) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        try:
            b = refs.find_bundle(env, bundle_id)
        except (sx.MainDbUnreadable, sqlite3.Error) as exc:
            raise db_guard(exc) from exc
        ready = refs.reachable(b)
        name = Path(b.locations[0].where).name if b.locations else None
        return {"bundle": _bundle_row(b), "file_name": name, "encrypted": bool(name and name.endswith(".age")),
                "manifest": _plain_summary(ready[0][1]) if ready else None}

    return await asyncio.to_thread(work)


async def contents(ctx: Any, ref: CrateRef, identity: Optional[str] = None) -> Dict[str, Any]:
    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        key = refs.parse_identity(identity)
        found = resolve(env, ref)
        with refs.open_reader(found.path, key) as reader:
            try:
                return refs.contents(reader)
            except cf.CrateError as exc:
                raise invalid("crate_unreadable", f"{exc.code}: the crate could not be read") from exc

    return await asyncio.to_thread(work)


async def extract(ctx: Any, ref: CrateRef, conversation_id: str, identity: Optional[str] = None) -> Dict[str, Any]:
    if not K.CONVERSATION_ID_RE.match(conversation_id or ""):
        raise invalid("bad_conversation_id", "the conversation id is not one a crate can hold")

    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        key = refs.parse_identity(identity)
        found = resolve(env, ref)
        extracts.prune_extracts(env.work)
        homes = [Path(h) for h in env.locations.claude_homes()] + [Path(env.locations.codex_home())]
        with refs.open_reader(found.path, key) as reader:
            try:
                out = cf.extract_conversation(reader, conversation_id, extracts.new_extract_dest(env.work),
                                              enc_for=slugify_project_dir, forbidden_roots=homes)
            except cf.ConversationNotInCrate as exc:
                raise not_found("conversation_not_in_crate", f"the crate holds no conversation {conversation_id}") from exc
            except cf.CrateError as exc:
                raise invalid("crate_unreadable", f"{exc.code}: the conversation could not be extracted") from exc
        return {"dest": str(out.dest), "files": list(out.files), "enc_folder": out.enc_folder,
                "resume_hint": out.resume_hint}

    return await asyncio.to_thread(work)


class _Progress:

    def __init__(self, handle: JobHandle) -> None:
        self.handle, self.last = handle, 0

    def __call__(self, processed: int) -> None:
        self.handle.check()
        if processed < self.last:
            self.last = 0
        self.handle.add(processed - self.last)
        self.last = processed


def _verify_one(env: CrateEnv, handle: JobHandle, path: Path, level: str, expected: Optional[str],
                key: Optional[bytes]) -> cf.VerifyReport:
    scratch = extracts.new_drill_scratch(env.work) if level == "drill" else None
    if scratch is not None:
        handle.temp(str(scratch))
    try:
        return cf.verify(path, level, expected_sha256=expected, identity=key, progress=_Progress(handle),
                         scratch=scratch)
    finally:
        if scratch is not None:
            extracts.remove_folder(scratch)
            handle.untemp(str(scratch))


def _record_folder_pass(env: CrateEnv, path: Path, report: cf.VerifyReport, key: Optional[bytes]) -> Optional[str]:
    now = time.time()
    known = refs.all_bundles(env)
    match = next((b for b in known if b.sha256 == report.bundle_sha256), None)
    if match is not None:
        record.add_location(env, match.bundle_id, str(path), now)
        if report.level != "quick":
            record.mark_verified(env, match.bundle_id, str(path), report.level, now)
        return match.bundle_id
    if report.level == "quick":
        return None
    with cf.open_crate(path, key) as reader:
        manifest = reader.manifest
    install_id, _machine = cs.install_identity(state_dir=env.state)
    if manifest.variant != "own" or not install_id or manifest.source.get("install_id") != install_id:
        return None
    if manifest.bundle_id in {b.bundle_id for b in known}:
        return None
    record.record_published(env, record.manifest_record(manifest, path, report.bundle_sha256, report.bytes), now)
    return manifest.bundle_id


Targets = Tuple[List[Tuple[Path, Optional[str]]], Optional[sx.Bundle]]


def _targets(env: CrateEnv, ref: CrateRef, location: Optional[int]) -> Targets:
    found = resolve(env, ref, location)
    if found.bundle is None or location is not None:
        return [(found.path, found.expected_sha256)], found.bundle
    return [(path, found.bundle.sha256) for _i, path in refs.reachable(found.bundle)], found.bundle


async def start_verify(ctx: Any, ref: CrateRef, level: str, location: Optional[int] = None,
                       identity: Optional[str] = None) -> Dict[str, str]:
    if level not in cf.LEVELS:
        raise invalid("bad_level", "level is quick, full or drill")

    def run() -> Dict[str, str]:
        env = service.env_of(ctx)
        key = refs.parse_identity(identity)
        targets, found = _targets(env, ref, location)

        def work(handle: JobHandle) -> Dict[str, Any]:
            handle.phase(K.PHASE_VERIFYING, total=sum(os.path.getsize(p) for p, _s in targets), files=len(targets))
            results: List[Dict[str, Any]] = []
            for path, expected in targets:
                report = _verify_one(env, handle, path, level, expected, key)
                results.append({"where": str(path), **report.as_json()})
                handle.add(0, files=1)
            failed = [r for r in results if not r["ok"]]
            if failed:
                raise JobFailed(failed[0]["problems"][0]["code"], {"locations": results})
            recorded = None
            for r in results:
                if found is not None:
                    record.mark_verified(env, found.bundle_id, r["where"], level, time.time())
                    recorded = found.bundle_id
                else:
                    recorded = _record_folder_pass(env, Path(r["where"]), _report_of(r), key)
            return {"level": level, "locations": results, "recorded": recorded}

        return {"job_id": service.start_job(ctx, env, K.KIND_VERIFY, {**ref.as_json(), "level": level,
                                                                       "location": location}, work)}

    return await asyncio.to_thread(run)


def _report_of(row: Dict[str, Any]) -> cf.VerifyReport:
    return cf.VerifyReport(ok=bool(row["ok"]), level=str(row["level"]), encrypted=bool(row["encrypted"]),
                           bundle_sha256=str(row["bundle_sha256"]), content_id=row.get("content_id"),
                           bytes=int(row.get("bytes") or 0))


def _sidecars(src: Path) -> List[Tuple[str, bytes]]:
    out = []
    for suffix in _SIDECARS:
        side = src.parent / f"{src.name}{suffix}"
        if side.is_file() and not side.is_symlink():
            out.append((side.name, side.read_bytes()))
    return out


async def start_copy(ctx: Any, bundle_id: str, identity: Optional[str] = None) -> Dict[str, str]:
    def run() -> Dict[str, str]:
        env = service.env_of(ctx)
        key = refs.parse_identity(identity)
        found = resolve(env, CrateRef(bundle_id=bundle_id))
        try:
            second = folders.resolve(env, K.FOLDER_SECOND)
        except folders.FolderUnavailable as exc:
            raise conflict(exc.code, exc.detail) from exc
        b = found.bundle
        if b is None:
            raise not_found("bundle_not_found", f"no bundle {bundle_id}")

        def work(handle: JobHandle) -> Dict[str, Any]:
            handle.phase(K.PHASE_COPYING, total=os.path.getsize(found.path), files=1)
            final = copy_crate(found.path, second, b.sha256, handle, identities=[key] if key else [],
                               sidecars=_sidecars(found.path))
            level = "quick" if found.encrypted and not key else "full"
            now = time.time()
            record.add_location(env, b.bundle_id, str(final), now)
            if level == "full":
                record.mark_verified(env, b.bundle_id, str(final), level, now)
            return {"bundle_id": b.bundle_id, "path": str(final), "level": level}

        return {"job_id": service.start_job(ctx, env, K.KIND_COPY, {"bundle_id": bundle_id, "folder": K.FOLDER_SECOND},
                                            work)}

    return await asyncio.to_thread(run)


def bundle_id_of(name: str) -> str:
    for suffix in (".crate.age", ".crate"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


async def folder_crates(ctx: Any, folder: str) -> Dict[str, Any]:
    if folder not in (K.FOLDER_PRIMARY, K.FOLDER_SECOND):
        raise invalid("bad_folder", "folder is primary or second")

    def work() -> Dict[str, Any]:
        env = service.env_of(ctx)
        try:
            base = folders.resolve(env, folder)
        except folders.FolderUnavailable as exc:
            raise conflict(exc.code, exc.detail) from exc
        ids = {b.bundle_id for b in known_bundles(env)}
        return {"crates": [{"name": c.name, "size": c.size, "mtime": c.mtime, "share": c.share,
                            "encrypted": c.name.endswith(".age"), "sha256_sidecar": c.sha256_sidecar,
                            "bundle_id": bundle_id_of(c.name) if bundle_id_of(c.name) in ids else None,
                            "project_root": refs.project_root_of(base / (K.SHARE_SUBFOLDER if c.share else "") / c.name)}
                           for c in folders.scan(base)]}

    return await asyncio.to_thread(work)
