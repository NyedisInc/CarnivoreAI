
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import restore
from src.cplugs.save.vault.describe import describe
from src.cplugs.save.vault.manifest import Manifest, ManifestError, check_unit
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import transcript_files as tf

SESSION_INDEX_TTL: float = 30.0
_MAIN_ROLES = (K.ROLE_TRANSCRIPT, K.ROLE_CODEX_ROLLOUT)


class PinnedError(RuntimeError):
    pass


class UnknownPoint(LookupError):
    pass


def list_points(vault: Vault, unit: str) -> List[Dict[str, Any]]:
    check_unit(unit)
    return [describe(m, vault.manifests.is_pinned(unit, m.point_id), _tags(vault, unit, m.point_id)) for m in reversed(vault.manifests.points(unit))]


def _tags(vault: Vault, unit: str, point_id: str) -> Dict[str, Any]:
    try:
        return vault.manifests.read_tags(unit, point_id)
    except ManifestError:
        return {}


def read_point(vault: Vault, unit: str, point_id: str) -> Manifest:
    check_unit(unit)
    if point_id not in vault.manifests.point_ids(unit):
        raise UnknownPoint(f"no restore point {point_id} for conversation {unit}")
    return vault.manifests.read(unit, point_id)


def set_pinned(vault: Vault, unit: str, point_id: str, pinned: bool) -> bool:
    read_point(vault, unit, point_id)
    vault.manifests.set_pinned(unit, point_id, pinned)
    vault.changed()
    return pinned


def delete_point(vault: Vault, unit: str, point_id: str) -> int:
    read_point(vault, unit, point_id)
    if vault.manifests.is_pinned(unit, point_id):
        raise PinnedError(f"{point_id} is pinned; unpin it first")
    vault.manifests.delete(unit, point_id)
    vault.changed()
    return 0


@dataclass(frozen=True)
class PointRestore:

    status: str
    transcript_path: Path
    subagents_written: int
    subagents_skipped: int
    conversation_id: str
    working_dir: Optional[str]
    wrapper: Optional[str]
    session_uuid: Optional[str]


def restore_point(vault: Vault, unit: str, point_id: str, homes: Dict[str, Path]) -> PointRestore:
    manifest = read_point(vault, unit, point_id)
    full = {"codex": tf.default_codex_home(), "state": Path(tf.state_dir()), **{k: Path(v) for k, v in homes.items()}}
    projects = full.get("claude/projects", full["claude"] / "projects")
    main = manifest.main()
    if main is None:
        raise restore.RestoreError("this point holds no transcript to put back")
    present = tf.family_conversation_presence(manifest.family, unit, working_dir=manifest.working_dir,
                                              corpus_root=projects, codex_home=str(full["codex"]))
    if present.outcome == tf.CONVERSATION_PRESENT and present.path is not None:
        if not restore.file_matches(present.path, main):
            raise restore.RestoreConflict([present.path])
        status, path = restore.STATUS_ALREADY_PRESENT, present.path
    else:
        done = restore.restore_to_homes(vault.blobs, manifest, full, only_roles=_MAIN_ROLES)
        status, path = restore.STATUS_WRITTEN, (done.written or [full[main.home] / main.rel])[0]
    rest = restore.restore_to_homes(vault.blobs, manifest, full, skip_conflicts=True,
                                    only_roles=[e.role for e in manifest.files if e.role not in _MAIN_ROLES])
    return PointRestore(status, path, len(rest.written), len(rest.already_present) + len(rest.skipped_conflicts), unit,
                        manifest.working_dir, manifest.wrapper, manifest.session_uuid)


class SessionIndex:

    def __init__(self, clock=time.monotonic) -> None:
        self._clock, self._lock = clock, threading.Lock()
        self._at = float("-inf")
        self._root: Optional[Path] = None
        self._map: Dict[str, List[str]] = {}

    def conversations(self, vault: Vault, session_uuid: str) -> List[str]:
        with self._lock:
            if self._root != vault.root or self._clock() - self._at > SESSION_INDEX_TTL:
                mapping: Dict[str, List[str]] = {}
                for unit in vault.manifests.units():
                    point = vault.manifests.newest(unit)
                    if point is not None and point.session_uuid and unit not in mapping.setdefault(point.session_uuid, []):
                        mapping[point.session_uuid].append(unit)
                self._map, self._root, self._at = mapping, vault.root, self._clock()
            return list(self._map.get(session_uuid, []))


SESSIONS = SessionIndex()
