
from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Any, List, Tuple

from fastapi.responses import FileResponse

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders, refs, service
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import conflict, invalid, not_found
from src.cplugs.crate.refs import CrateRef

PART_CRATE, PART_SHA256 = "crate", "sha256"
PARTS = (PART_CRATE, PART_SHA256)
SIDECAR_SUFFIX = ".sha256"
SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


def _configured_parents(env: CrateEnv) -> List[str]:
    out: List[str] = []
    for which in (K.FOLDER_PRIMARY, K.FOLDER_SECOND):
        try:
            base = folders.resolve(env, which)
        except folders.FolderUnavailable:
            continue
        out += [os.path.realpath(base), os.path.realpath(base / K.SHARE_SUBFOLDER)]
    return out


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _crate_path(env: CrateEnv, ref: CrateRef) -> Path:
    if ref.folder:
        return refs.resolve_ref(env, ref).path
    parents = _configured_parents(env)
    found = refs.find_bundle(env, str(ref.bundle_id))
    present = refs.reachable(found)
    if not present:
        refs.resolve_ref(env, ref)
    for _index, path in present:
        if os.path.realpath(path.parent) in parents and K.CRATE_NAME_RE.match(path.name):
            return path
    raise conflict("bundle_not_in_folder", f"bundle {ref.bundle_id} has no copy in a configured crates folder")


def locate_blocking(env: CrateEnv, ref: CrateRef, part: str) -> Tuple[Path, str]:
    if part not in PARTS:
        raise invalid("bad_part", "part is crate or sha256")
    path = _crate_path(env, ref)
    if part == PART_CRATE:
        return path, path.name
    side = path.with_name(path.name + SIDECAR_SUFFIX)
    if not _regular(side):
        raise not_found("sidecar_not_found", f"{path.name} has no {SIDECAR_SUFFIX} file beside it")
    return side, side.name


async def download(ctx: Any, ref: CrateRef, part: str = PART_CRATE) -> FileResponse:
    path, name = await asyncio.to_thread(lambda: locate_blocking(service.env_of(ctx), ref, part))
    return FileResponse(path, media_type="application/octet-stream", filename=name, content_disposition_type="attachment",
                        headers=SAFE_HEADERS)
