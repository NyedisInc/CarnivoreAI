
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.live_install_roots import CPLUG_CODE_DIR_NAME
from src.core.skills.validate_types import EXCLUDED_BASENAME_PREFIXES, EXCLUDED_BASENAMES
from src.cplugs.host.sidecar_manifest import SidecarManifest, SidecarManifestError, load_sidecar_manifest
from src.cplugs.runtime.integrity import SIDECAR_NAME

logger = structlog.get_logger()

FILE_NAME = "sideload.json"
DURATION_HOURS = (1, 12, 24, 168)
DEFAULT_HOURS = 12
TTL_SECONDS = DEFAULT_HOURS * 60 * 60
LOCAL_PUBLISHER = "local"
TIER_LOCAL = "local"
MAX_FILES = 2000
MAX_BYTES = 20 * 1024 * 1024
_SKIP_DIRS = frozenset({"__pycache__", ".git"})
_SKIP_SUFFIXES = (".pyc", ".pyo")

_lock = threading.RLock()
_snapshots: Dict[Path, Tuple[Tuple[int, int, int, int], Mapping[str, Any]]] = {}
_EMPTY: Mapping[str, Any] = MappingProxyType({})


def wall() -> float:
    return time.time()


class SideloadRefused(Exception):

    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code, self.status = code, status


def as_local(manifest: SidecarManifest) -> SidecarManifest:
    return replace(manifest, tier=TIER_LOCAL)


def is_local(item_id: str) -> bool:
    return item_id.partition("/")[0] == LOCAL_PUBLISHER


def switch_path(state_dir: Path) -> Path:
    return Path(state_dir) / "cplugs" / FILE_NAME


def code_root_of(state_dir: Path, name: str) -> Path:
    return Path(state_dir) / CPLUG_CODE_DIR_NAME / name


def _load(state_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(switch_path(state_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("cplug_sideload_unreadable", error_type=type(exc).__name__)
        return None
    return data if isinstance(data, dict) else {}


def _read(state_dir: Path) -> Dict[str, Any]:
    data = _load(state_dir)
    return {} if data is None else data


def _write(state_dir: Path, data: Dict[str, Any]) -> bool:
    try:
        return atomic_write_json(switch_path(state_dir), data, log_event="cplug_sideload_write_failed")
    finally:
        _snapshots.pop(switch_path(state_dir), None)


def _snapshot(state_dir: Path) -> Mapping[str, Any]:
    path = switch_path(state_dir)
    try:
        st = path.stat()
    except OSError:
        _snapshots.pop(path, None)
        return _EMPTY
    signature = (st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)
    cached = _snapshots.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1]
    data = _load(state_dir)
    if data is None:
        _snapshots.pop(path, None)
        return _EMPTY
    view = MappingProxyType(data)
    _snapshots[path] = (signature, view)
    return view


def valid_duration(hours: object) -> bool:
    return hours is None or (type(hours) is int and hours in DURATION_HOURS)


def _hours_in(data: Mapping[str, Any]) -> Optional[int]:
    if "hours" not in data:
        return DEFAULT_HOURS
    found = data["hours"]
    return found if valid_duration(found) else DEFAULT_HOURS


def _enabled_in(data: Mapping[str, Any]) -> Optional[float]:
    stamp = data.get("enabled_at")
    return float(stamp) if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else None


def _expiry_in(data: Mapping[str, Any]) -> Optional[float]:
    stamp, hours = _enabled_in(data), _hours_in(data)
    return stamp + hours * 3600 if stamp is not None and hours is not None else None


def duration_hours(state_dir: Path) -> Optional[int]:
    return _hours_in(_snapshot(state_dir))


def _enabled_at(state_dir: Path) -> Optional[float]:
    return _enabled_in(_snapshot(state_dir))


def expires_at(state_dir: Path) -> Optional[float]:
    return _expiry_in(_snapshot(state_dir))


def is_on(state_dir: Path, now: Optional[Callable[[], float]] = None) -> bool:
    data = _snapshot(state_dir)
    if _enabled_in(data) is None:
        return False
    end = _expiry_in(data)
    return end is None or (now or wall)() < end


def set_switch(state_dir: Path, on: bool, now: Optional[Callable[[], float]] = None, hours: Optional[int] = DEFAULT_HOURS) -> bool:
    if on and not valid_duration(hours):
        raise SideloadRefused("duration_invalid", f"the duration is one of {list(DURATION_HOURS)} hours, or null for until turned off", 422)
    with _lock:
        data = _read(state_dir)
        data["enabled_at"] = (now or wall)() if on else None
        if on:
            data["hours"] = hours
        data.setdefault("items", {})
        return _write(state_dir, data)


def items(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found = _read(state_dir).get("items")
    return {n: v for n, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def forget(state_dir: Path, name: str) -> None:
    with _lock:
        data = _read(state_dir)
        if isinstance(data.get("items"), dict) and data["items"].pop(name, None) is not None and not _write(state_dir, data):
            raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)


def installs(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found = _read(state_dir).get("installs")
    return {k: v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def put_install(state_dir: Path, record: Dict[str, Any]) -> None:
    with _lock:
        data = _read(state_dir)
        data.setdefault("items", {})
        data.setdefault("installs", {})[f"{record['kind']}/{record['name']}"] = record
        if not _write(state_dir, data):
            raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)


def forget_install(state_dir: Path, kind: str, name: str) -> None:
    with _lock:
        data = _read(state_dir)
        if isinstance(data.get("installs"), dict) and data["installs"].pop(f"{kind}/{name}", None) is not None and not _write(state_dir, data):
            raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)


def _copy_one(dirfd: int, name: str, dest: Path, budget: int) -> Tuple[str, int]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
    except OSError as exc:
        raise SideloadRefused("source_unsafe", "the folder holds a link or a file that cannot be opened safely", 422) from exc
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise SideloadRefused("source_unsafe", "the folder holds a link, a special file or a hard-linked file; sideload copies real files only", 422)
        if info.st_size > budget:
            raise SideloadRefused("source_too_big", f"a sideload is capped at {MAX_FILES} files and {MAX_BYTES // 1048576} MB", 422)
        data = handle.read(info.st_size + 1)
    if len(data) != info.st_size:
        raise SideloadRefused("source_unsafe", "a file changed while it was being copied", 422)
    with open(dest, "xb") as out:
        out.write(data)
    os.chmod(dest, 0o755 if info.st_mode & stat.S_IXUSR else 0o644)
    return hashlib.sha256(data).hexdigest(), info.st_size


def is_noise(name: str) -> bool:
    return name in EXCLUDED_BASENAMES or name.startswith(EXCLUDED_BASENAME_PREFIXES)


def copy_tree(source: Path, dest: Path) -> Dict[str, str]:
    files: Dict[str, str] = {}
    total = 0
    pending: set = set()
    dest.mkdir(parents=True)
    for root, dirs, names, dirfd in os.fwalk(source, follow_symlinks=False):
        rel_root = Path(root).relative_to(source)
        pending.discard(rel_root.as_posix())
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for d in dirs:
            if not stat.S_ISDIR(os.stat(d, dir_fd=dirfd, follow_symlinks=False).st_mode):
                raise SideloadRefused("source_unsafe", "the folder holds a link; sideload copies real files only", 422)
            (dest / rel_root / d).mkdir(parents=True, exist_ok=True)
            pending.add((rel_root / d).as_posix())
        for n in sorted(names):
            if n.endswith(_SKIP_SUFFIXES) or is_noise(n):
                continue
            if not stat.S_ISREG(os.stat(n, dir_fd=dirfd, follow_symlinks=False).st_mode):
                raise SideloadRefused("source_unsafe", "the folder holds a link or special file; sideload copies real files only", 422)
            if len(files) >= MAX_FILES:
                raise SideloadRefused("source_too_big", f"a sideload is capped at {MAX_FILES} files and {MAX_BYTES // 1048576} MB", 422)
            rel = rel_root / n
            files[rel.as_posix()], size = _copy_one(dirfd, n, dest / rel, MAX_BYTES - total)
            total += size
    if pending:
        raise SideloadRefused("source_unsafe", "a folder changed while it was being copied", 422)
    return files


def changed_files(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def stage(state_dir: Path, name: str, source: Path) -> "tuple[Path, Dict[str, str], SidecarManifest]":
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise SideloadRefused("source_missing", "give the absolute path of a folder (not a link)", 422)
    staging = code_root_of(state_dir, f".sideload-{name}-{os.getpid()}-{time.monotonic_ns()}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        files = copy_tree(source, staging)
        (staging / SIDECAR_NAME).unlink(missing_ok=True)
        files.pop(SIDECAR_NAME, None)
        manifest = as_local(load_sidecar_manifest(staging, name))
    except SidecarManifestError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise SideloadRefused("manifest_invalid", str(exc), 422) from exc
    except (SideloadRefused, OSError):
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging, files, manifest


def unchanged(state_dir: Path, name: str, digest: str) -> bool:
    return items(state_dir).get(name, {}).get("digest") == digest and code_root_of(state_dir, name).is_dir()


def touch(state_dir: Path, name: str, source: Path, now: Optional[Callable[[], float]] = None) -> None:
    with _lock:
        data = _read(state_dir)
        data["items"][name]["synced_at"] = (now or wall)()
        data["items"][name]["source"] = str(source)
        if not _write(state_dir, data):
            raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)


def install_staged(state_dir: Path, name: str, staging: Path, files: Dict[str, str], digest: str, source: Path,
                   now: Optional[Callable[[], float]] = None) -> List[str]:
    root = code_root_of(state_dir, name)
    old = code_root_of(state_dir, f".sideload-old-{name}-{os.getpid()}")
    with _lock:
        data = _read(state_dir)
        data.setdefault("items", {})
        previous = data["items"].get(name)
        changed = changed_files(previous.get("files", {}) if isinstance(previous, dict) else {}, files)
        if root.exists():
            os.replace(root, old)
        os.replace(staging, root)
        shutil.rmtree(old, ignore_errors=True)
        data["items"][name] = {"files": files, "digest": digest, "changed": changed, "source": str(source), "synced_at": (now or wall)()}
        if not _write(state_dir, data):
            raise SideloadRefused("sideload_not_saved", "the sideload record could not be written", 500)
    return changed
