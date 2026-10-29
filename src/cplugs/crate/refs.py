
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import CrateApiError, conflict, invalid, not_found
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import exports as sx

BUNDLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$"
MAX_IDENTITY_CHARS = 200


@dataclass(frozen=True)
class CrateRef:

    bundle_id: Optional[str] = None
    folder: Optional[str] = None
    name: Optional[str] = None

    def as_json(self) -> Dict[str, Any]:
        return {"bundle_id": self.bundle_id} if self.bundle_id else {"folder": self.folder, "name": self.name}


@dataclass(frozen=True)
class Resolved:

    path: Path
    bundle: Optional[sx.Bundle]
    expected_sha256: Optional[str]

    @property
    def encrypted(self) -> bool:
        return self.path.name.endswith(".age")


def location_state(where: str) -> str:
    parts = Path(where).parts
    if len(parts) >= 3 and parts[1] == K.VOLUMES_ROOT.strip("/") and not os.path.ismount(os.path.join(*parts[:3])):
        return K.FOLDER_UNMOUNTED
    try:
        st = os.lstat(where)
    except OSError:
        return K.LOCATION_MISSING
    return K.LOCATION_PRESENT if stat.S_ISREG(st.st_mode) else K.LOCATION_MISSING


def bundle_view(b: sx.Bundle) -> Dict[str, Any]:
    return {"bundle_id": b.bundle_id, "sha256": b.sha256, "scope": b.scope, "project_uid": b.project_uid,
            "session_uuid": b.session_uuid, "label": b.label, "created_at": sx.iso_utc(b.created_at),
            "locations": [{"where": loc.where, "verified_at": sx.iso_utc(loc.verified_at),
                           "state": location_state(loc.where)} for loc in b.locations],
            "verified_at": sx.iso_utc(b.verified_at), "local_removed": b.local_removed,
            "conversations": b.conversations}


def all_bundles(env: CrateEnv) -> List[sx.Bundle]:
    return sx.with_main_db(sx.list_bundles, state=env.state)


def find_bundle(env: CrateEnv, bundle_id: str) -> sx.Bundle:
    def work(conn: Any) -> sx.Bundle:
        return sx.bundle(conn, bundle_id)

    try:
        return sx.with_main_db(work, state=env.state)
    except sx.BundleNotFound as exc:
        raise not_found("bundle_not_found", f"no bundle {bundle_id}") from exc


def reachable(b: sx.Bundle) -> List[Tuple[int, Path]]:
    return [(i, Path(loc.where)) for i, loc in enumerate(b.locations) if location_state(loc.where) == K.LOCATION_PRESENT]


def _unreachable(b: sx.Bundle) -> CrateApiError:
    return conflict("bundle_unreachable", [{"where": loc.where, "state": location_state(loc.where)}
                                           for loc in b.locations])


def _folder_crate(env: CrateEnv, folder: str, name: str) -> Path:
    if folder not in (K.FOLDER_PRIMARY, K.FOLDER_SECOND):
        raise invalid("bad_folder", "folder is primary or second")
    if not K.CRATE_NAME_RE.match(name or ""):
        raise invalid("bad_crate_name", "the name is not a crate file name")
    try:
        base = folders.resolve(env, folder)
    except folders.FolderUnavailable as exc:
        raise conflict(exc.code, exc.detail) from exc
    parent = base / K.SHARE_SUBFOLDER if name.startswith(K.PREFIX_SHARE + "-") else base
    path = parent / name
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise not_found("crate_not_found", f"no crate {name} in the {folder} folder") from exc
    if not stat.S_ISREG(st.st_mode) or os.path.realpath(path.parent) != os.path.realpath(parent):
        raise invalid("crate_refused", f"{name} is not a regular crate file in the {folder} folder")
    return path


def resolve_ref(env: CrateEnv, ref: CrateRef, location: Optional[int] = None) -> Resolved:
    if ref.bundle_id:
        b = find_bundle(env, ref.bundle_id)
        ready = reachable(b)
        if location is not None:
            if not 0 <= location < len(b.locations):
                raise not_found("location_not_found", f"bundle {b.bundle_id} has no location {location}")
            ready = [(i, p) for i, p in ready if i == location]
        if not ready:
            raise _unreachable(b)
        return Resolved(ready[0][1], b, b.sha256)
    path = _folder_crate(env, str(ref.folder), str(ref.name))
    return Resolved(path, None, cf.expected_from_sidecar(path))


def parse_identity(text: Optional[str]) -> Optional[bytes]:
    if text is None or not text.strip():
        return None
    if len(text) > MAX_IDENTITY_CHARS:
        raise invalid("identity_invalid", "the identity is not an age secret key")
    try:
        return cf.parse_identity(text.strip())
    except cf.KeyFormatError as exc:
        raise invalid("identity_invalid", "the identity is not an age secret key") from exc


def open_reader(path: Path, identity: Optional[bytes]) -> cf.CrateReader:
    try:
        return cf.open_crate(path, identity)
    except cf.NeedsIdentity as exc:
        raise conflict("needs_identity", "this crate is encrypted; an age identity is needed to read it") from exc
    except cf.WrongKey as exc:
        raise CrateApiError(403, "wrong_key", "the identity does not open this crate") from exc
    except cf.CrateError as exc:
        raise invalid("crate_unreadable", f"{exc.code}: the crate could not be read") from exc


_ROOT_CACHE: Dict[Tuple[str, int, int], Optional[str]] = {}
_ROOT_CACHE_MAX = 512


def project_root_of(path: Path) -> Optional[str]:
    if path.name.endswith(".age"):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key in _ROOT_CACHE:
        return _ROOT_CACHE[key]
    try:
        with cf.open_crate(path) as reader:
            root = reader.manifest.scope.get("project_root")
    except (OSError, cf.CrateError):
        return None
    value = root if isinstance(root, str) and root else None
    if len(_ROOT_CACHE) >= _ROOT_CACHE_MAX:
        _ROOT_CACHE.clear()
    _ROOT_CACHE[key] = value
    return value


def manifest_summary(m: cf.CrateManifest) -> Dict[str, Any]:
    return {"format_version": list(m.format_version), "variant": m.variant, "created_at": m.created_at,
            "bundle_id": m.bundle_id, "label": m.label,
            "conversations": [{"id": c.id, "family": c.family, "title": c.title, "origin": c.origin, "resume": c.resume}
                              for c in m.conversations],
            "counts": m.counts, "excluded_count": len(m.excluded), "warnings": list(m.warnings), "secrets": m.secrets}


def contents(reader: cf.CrateReader) -> Dict[str, Any]:
    return {"manifest": manifest_summary(reader.manifest),
            "files": [{"role": f.role, "home": f.home, "rel": f.rel, "length": f.length,
                       "conversation_id": f.conversation_id} for f in reader.files()],
            "tables": {store: {table: rec.rows for table, rec in sorted(tables.items())}
                       for store, tables in sorted(reader.tables().items())}}
