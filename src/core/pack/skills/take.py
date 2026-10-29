
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.pack.skills import owner, take_export
from src.core.pack.skills.bundle import Bundle, BundleError, read_bundle
from src.core.pack.skills.scan import SkillScan, scan_skill
from src.core.pack.transport import blobs
from src.core.skills.digest import DigestEntry, digest_entries

logger = structlog.get_logger()

EXPORT_PATH = "/federation/pack/skills/export"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class TakeError(Exception):

    def __init__(self, code: str, status: int = 409, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.status, self.detail = code, status, detail


@dataclass(frozen=True)
class Taken:

    bundle: Bundle
    scan: SkillScan
    stage: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.stage, ignore_errors=True)


def _code(answer: Any) -> str:
    detail = answer.get("detail") if isinstance(answer, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else ""


async def _download(request: Any, listing: Any, target: Path) -> None:
    blob_id, size, sha = (listing.get(k) if isinstance(listing, dict) else None for k in ("blob_id", "size", "sha256"))
    if (not blobs.valid_id(blob_id) or type(size) is not int or not 0 < size <= take_export.MAX_EXPORT_BYTES
            or not isinstance(sha, str) or not _SHA_RE.match(sha)):
        raise TakeError("bad_answer")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    got = 0
    with os.fdopen(fd, "wb") as out:
        while got < size:
            status, answer = await request("GET", f"{EXPORT_PATH}/{blob_id}?offset={got}")
            if status != 200 or not isinstance(answer, dict) or answer.get("offset") != got:
                raise TakeError("bad_answer")
            raw = answer.get("data")
            if not isinstance(raw, str) or len(raw) > take_export.CHUNK_BYTES * 4 // 3 + 8:
                raise TakeError("bad_answer")
            try:
                chunk = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                raise TakeError("bad_answer") from None
            if not chunk or len(chunk) > take_export.CHUNK_BYTES or got + len(chunk) > size or hashlib.sha256(chunk).hexdigest() != answer.get("sha256"):
                raise TakeError("bad_answer")
            out.write(chunk)
            got += len(chunk)
    if blobs.file_sha256(str(target)) != sha:
        raise TakeError("bad_answer")


async def fetch_copy(request: Any, family: str, name: str, stage_root: Path) -> Taken:
    from src.core.federation.peer_client import PeerRefused, PeerUnreachable

    take_export.purge(stage_root)
    stage = stage_root / f"take-{secrets.token_hex(6)}"
    stage.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(stage, 0o700)
    blob_id: Optional[str] = None
    try:
        try:
            status, listing = await request("POST", EXPORT_PATH, json={"family": family, "name": name})
            if status != 200:
                code = _code(listing)
                raise TakeError(code or "refused", 404 if status == 404 else 409)
            blob_id = listing.get("blob_id") if isinstance(listing, dict) else None
            archive = stage / "copy.tgz"
            await _download(request, listing, archive)
        except (PeerUnreachable, PeerRefused, TimeoutError, asyncio.TimeoutError) as exc:
            logger.info("pack_skills_take_unreachable", error=type(exc).__name__)
            raise TakeError("unreachable") from None
        except OSError as exc:
            logger.warning("pack_skills_take_stage_failed", errno=exc.errno)
            raise TakeError("cannot_write", 503) from None
        finally:
            if blobs.valid_id(blob_id):
                try:
                    await request("POST", f"{EXPORT_PATH}/{blob_id}/done", json={})
                except (PeerUnreachable, PeerRefused, TimeoutError, asyncio.TimeoutError):
                    pass
        try:
            bundle = await asyncio.to_thread(read_bundle, archive, stage / "tree")
        except BundleError as exc:
            raise TakeError("bad_bundle", detail=exc.code) from None
        if set(bundle.skills) != {(family, name)}:
            raise TakeError("bad_bundle", detail="not the skill asked for")
        scan = await asyncio.to_thread(scan_skill, bundle.staging / family / name, name)
        if scan.problem is not None:
            raise TakeError("skill_held", detail=scan.problem)
        if digest_entries(DigestEntry(e.path, e.mode, e.sha256) for e in bundle.skills[(family, name)]) != scan.digest:
            raise TakeError("bad_bundle", detail="hash_mismatch")
        return Taken(bundle, scan, stage)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def local_state(roots: list[Any], family: str, name: str) -> list[list[str]]:
    from src.core.pack.skills.targets import roots_for
    from src.core.skills.records import SIDECAR_NAME

    out: list[list[str]] = []
    for root in roots_for(roots, family):
        target = root.leaf / name
        try:
            if root.problem:
                state = "root:" + root.problem
            elif not os.path.lexists(target):
                state = "absent"
            elif target.is_symlink():
                state = "link"
            elif os.path.lexists(target / SIDECAR_NAME):
                state = "catalog"
            else:
                mine = scan_skill(target, name)
                state = mine.digest if mine.problem is None else "held:" + mine.problem
        except OSError:
            state = "unreadable"
        out.append([root.group, state])
    return out


def preview(taken: Taken, family: str, name: str, roots: list[Any]) -> dict[str, Any]:
    from src.core.pack.skills.targets import roots_for

    here = "absent"
    for root in roots_for(roots, family):
        if root.problem or not os.path.lexists(root.leaf / name):
            continue
        try:
            mine = scan_skill(root.leaf / name, name)
        except OSError:
            mine = SkillScan(name, problem="unreadable")
        here = "same" if mine.problem is None and mine.digest == taken.scan.digest else "differs"
        break
    files = taken.scan.files
    return {"family": family, "name": name, "digest": taken.scan.digest, "files": len(files), "bytes": sum(f.size for f in files),
            "scripts": owner.scripts_of(taken.scan),
            "here": here}
