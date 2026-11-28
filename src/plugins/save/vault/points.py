
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.plugins.save.vault import constants as K
from src.plugins.save.vault import restore
from src.plugins.save.vault.describe import describe
from src.plugins.save.vault.manifest import Manifest, ManifestError, check_unit
from src.plugins.save.offload import ledger as offload_ledger
from src.plugins.save.vault.store import Vault
from src.plugins.sdk import transcript_files as tf, vault_sources
from src.plugins.save.vault.manifest import codex_account_home_key, is_codex_account_home

SESSION_INDEX_TTL: float = 30.0
_MAIN_ROLES = (K.ROLE_TRANSCRIPT, K.ROLE_CODEX_ROLLOUT)


class PinnedError(RuntimeError):
    pass


class OffloadedError(RuntimeError):
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
    try:
        offloaded = offload_ledger.protects(vault.root, unit, point_id)
    except offload_ledger.LedgerUnreadable as exc:
        raise OffloadedError(f"the offload ledger cannot be read, so it is not known whether {point_id} backs an offloaded conversation: {exc}") from exc
    if offloaded:
        raise OffloadedError(f"{point_id} is the only copy of an offloaded conversation; restore the conversation first")
    vault.manifests.delete(unit, point_id)
    vault.changed()
    return 0

logger = structlog.get_logger()


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
    redirected_homes: Tuple[str, ...] = ()


def restore_point(vault: Vault, unit: str, point_id: str, homes: Dict[str, Path]) -> PointRestore:
    manifest = read_point(vault, unit, point_id)
    _refuse_offloaded(vault, unit)
    accounts = {codex_account_home_key(path, account_id): path for account_id, path in vault_sources.codex_account_homes()}
    full = {"codex": tf.default_codex_home(), "state": Path(tf.state_dir()), **accounts, **{k: Path(v) for k, v in homes.items()}}
    projects = full.get("claude/projects", full["claude"] / "projects")
    main = manifest.main()
    if main is None:
        raise restore.RestoreError("this point holds no transcript to put back")
    present = _presence(manifest, unit, projects, [full["codex"], *accounts.values()])
    if present.outcome == tf.CONVERSATION_PRESENT and present.path is not None:
        if not restore.file_matches(present.path, main):
            raise restore.RestoreConflict([present.path])
        status, path = restore.STATUS_ALREADY_PRESENT, present.path
    else:
        done = restore.restore_to_homes(vault.blobs, manifest, full, only_roles=_MAIN_ROLES)
        status, path = restore.STATUS_WRITTEN, (done.written or [restore.homes_destination(full)(main)])[0]
    redirected = tuple(sorted({f.home for f in manifest.files if is_codex_account_home(f.home) and f.home not in full}))
    if redirected:
        logger.info("vault_restore_redirected", unit=unit, point_id=point_id, homes=list(redirected), note="account home not configured here; restored to the default Codex home")
    rest = restore.restore_to_homes(vault.blobs, manifest, full, skip_conflicts=True,
                                    only_roles=[e.role for e in manifest.files if e.role not in _MAIN_ROLES])
    return PointRestore(status, path, len(rest.written), len(rest.already_present) + len(rest.skipped_conflicts), unit,
                        manifest.working_dir, manifest.wrapper, manifest.session_uuid,
                        redirected)


def _presence(manifest: Manifest, unit: str, projects: Path, codex_homes: List[Path]) -> Any:
    def ask(codex_home: Path) -> Any:
        return tf.family_conversation_presence(manifest.family, unit, working_dir=manifest.working_dir, corpus_root=projects, codex_home=str(codex_home))

    first = ask(codex_homes[0])
    if manifest.family != "codex":
        return first
    seen = {os.path.realpath(codex_homes[0])}
    answer = first
    for home in codex_homes[1:]:
        if answer.outcome == tf.CONVERSATION_PRESENT:
            break
        real = os.path.realpath(home)
        if real not in seen:
            seen.add(real)
            found = ask(home)
            answer = found if found.outcome == tf.CONVERSATION_PRESENT else answer
    return answer


def _refuse_offloaded(vault: Vault, unit: str) -> None:
    offloaded = offload_ledger.offloaded_units(vault.root, state_dir=Path(tf.state_dir()))
    if offloaded.unreadable:
        raise OffloadedError("the offload ledger cannot be read, so it is not known whether this conversation is offloaded; nothing was restored")
    if offloaded.holds(unit):
        raise OffloadedError(f"{unit} is offloaded; put it back with the offload restore (POST /offload/conversations/{unit}/restore), which brings back the copy its offload verified")


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
