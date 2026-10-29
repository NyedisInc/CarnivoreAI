
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.manifest import Manifest, ManifestError, ManifestStore
from src.cplugs.save.vault.summary import PointSummary, probe_of
from src.cplugs.sdk import exports as sx
from src.cplugs.sdk.blob_codec import Throttle

if TYPE_CHECKING:  # pragma: no cover
    from src.cplugs.save.vault.store import Vault

logger = structlog.get_logger()


def read_state(root: Path) -> Dict[str, Any]:
    try:
        data = json.loads((Path(root) / K.STATE_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("vault_state_unreadable", error=str(exc))
        return {}
    return data if isinstance(data, dict) else {}


def write_state(root: Path, state: Dict[str, Any]) -> None:
    layout.atomic_write_json(Path(root) / K.STATE_FILE, state)


def original_gone(newest: Union[Manifest, PointSummary]) -> bool:
    probe = probe_of(newest)
    return bool(probe) and not any(path and os.path.exists(path) for path in probe)


class ExportTimes(Dict[str, float]):
    """``{conversation_id: exported_at}`` for the exported conversations among those asked about.

    ``unreadable`` is True when the pointers could not be read (a database that exists but failed), so an absent id
    means "unknown", not "not exported".
    """

    unreadable: bool = False


def exported_conversations(conversation_ids: Iterable[str]) -> ExportTimes:
    found = ExportTimes()
    wanted = sorted({c for c in conversation_ids if c})
    if not wanted:
        return found
    try:
        pointers = sx.with_main_db(lambda conn: sx.pointers_for(conn, wanted))
    except sx.MainDbUnreadable as exc:
        found.unreadable = not exc.missing
    except sqlite3.Error as exc:
        logger.warning("vault_export_pointers_unreadable", error_type=type(exc).__name__, conversations=len(wanted))
        found.unreadable = True
    else:
        found.update({cid: pointer.exported_at for cid, pointer in pointers.items()})
    if found.unreadable:
        logger.warning("vault_export_pointers_unreadable", conversations=len(wanted),
                       note="conversation units are neither thinned nor replaced until the pointers can be read")
    return found


def conversation_of(unit: str, newest: Union[Manifest, PointSummary]) -> str:
    return newest.conversation_id or unit


def protection(vault: "Vault", unit: str, newest: Union[Manifest, PointSummary],
               exported: Optional[Mapping[str, float]] = None) -> Optional[str]:
    """Why every point of a unit is protected: ``original_gone``, ``export_unknown``, ``exported`` or None.

    ``exported`` alone (a legacy marker on a unit with no conversation) protects whole; a conversation's export protects
    only its source point (:func:`export_time`). ``export_unknown`` is a conversation whose pointers could not be read.
    Inputs: vault; unit; newest (its newest point, a manifest or its summary); exported (:func:`exported_conversations`,
    read once by the caller; None reads this unit's pointer now). Output: str | None.
    """
    conversation = conversation_of(unit, newest)
    if exported is None:
        exported = exported_conversations([conversation])
    if original_gone(newest):
        return "original_gone"
    if newest.conversation_id:
        return "export_unknown" if getattr(exported, "unreadable", False) and conversation not in exported else None
    return "exported" if vault.manifests.is_exported(unit) else None


def export_time(vault: "Vault", unit: str, newest: Union[Manifest, PointSummary],
                exported: Mapping[str, float]) -> Optional[float]:
    at = exported.get(conversation_of(unit, newest))
    return at if at is not None else vault.manifests.exported_at(unit)


def export_source(points: Sequence[PointSummary], exported_at: float) -> Optional[str]:
    if not points:
        return None
    at_or_before = [p for p in points if p.created_epoch <= exported_at]
    return (at_or_before[-1] if at_or_before else points[0]).point_id


def may_replace(vault: "Vault", unit: str, prior: Manifest) -> bool:
    exported = exported_conversations([conversation_of(unit, prior)])
    if protection(vault, unit, prior, exported) is not None:
        return False
    at = export_time(vault, unit, prior, exported)
    return at is None or prior.created_epoch > at


def _summary_logged(store: ManifestStore, unit: str, point_id: str) -> Optional[PointSummary]:
    try:
        return store.summary(unit, point_id)
    except ManifestError as exc:
        logger.error("vault_manifest_unreadable", unit=unit, point_id=point_id, error=str(exc))
        return None


def _newest_of(store: ManifestStore, unit: str, ids: List[str]) -> Tuple[Optional[PointSummary], int]:
    for index in range(len(ids) - 1, -1, -1):
        found = _summary_logged(store, unit, ids[index])
        if found is not None:
            return found, index
    return None, -1


_LAST_PROTECTION: Dict[str, Optional[str]] = {}


def _note_protection(unit: str, reason: Optional[str], points: int) -> None:
    if _LAST_PROTECTION.get(unit, None) == reason and unit in _LAST_PROTECTION:
        return
    _LAST_PROTECTION[unit] = reason
    if reason is not None:
        logger.info("vault_unit_protected", unit=unit, reason=reason, points=points)


_LAST_PROTECTION: Dict[str, Optional[str]] = {}


def _note_protection(unit: str, reason: Optional[str], points: int) -> None:
    if unit in _LAST_PROTECTION and _LAST_PROTECTION[unit] == reason:
        return
    _LAST_PROTECTION[unit] = reason
    if reason is not None:
        logger.info("vault_unit_protected", unit=unit, reason=reason, points=points)


def _drop(vault: "Vault", unit: str, points: List[PointSummary], max_points: int, *, one_copy: bool = False,
          spare: Optional[str] = None) -> List[str]:
    if len(points) <= (1 if one_copy else max_points):
        return []
    store = vault.manifests
    candidates = [p for p in points[:-1] if p.point_id != spare and not store.is_pinned(unit, p.point_id)
                  and not store.is_kept(unit, p.point_id)]
    candidates.sort(key=lambda p: (p.reason in K.LIFECYCLE_REASONS, p.created_epoch))
    dropped: List[str] = []
    for victim in (candidates if one_copy else candidates[: len(points) - max_points]):
        store.delete(unit, victim.point_id)
        dropped.append(victim.point_id)
    if dropped:
        logger.info("vault_points_thinned", unit=unit, dropped=len(dropped))
        vault.changed()
    return dropped


@dataclass
class _Tally:

    keep: Set[str]
    other: Set[str]
    counts: Dict[str, int]


def _walk_unit(vault: "Vault", unit: str, exported: Mapping[str, float], max_points: int, tally: Optional[_Tally]) -> List[str]:
    store = vault.manifests
    ids = store.point_ids(unit)
    store.summaries.prune(unit, ids)
    newest, newest_at = _newest_of(store, unit, ids)
    if newest is None:
        return []
    reason = protection(vault, unit, newest, exported)
    whole = reason is not None
    _note_protection(unit, reason, len(ids))
    survivors = [p for p in (_summary_logged(store, unit, pid) for pid in ids[:newest_at]) if p is not None] + [newest]
    at = export_time(vault, unit, newest, exported) if newest.conversation_id and not whole else None
    source = export_source(survivors, at) if at is not None else None
    dropped: List[str] = []
    if not whole:
        dropped = _drop(vault, unit, survivors, max_points, one_copy=bool(newest.conversation_id), spare=source)
        gone = set(dropped)
        survivors = [p for p in survivors if p.point_id not in gone]
    if tally is not None:
        tally.counts["units"] += 1
        tally.counts["points"] += len(survivors)
        tally.counts["protected_units"] += whole
        held_mask = history_mask = 0
        for index, point in enumerate(survivors):
            pinned = store.is_pinned(unit, point.point_id)
            tally.counts["pinned"] += pinned
            if whole or index == len(survivors) - 1 or pinned or point.point_id == source or store.is_kept(unit, point.point_id):
                held_mask |= point.mask
            else:
                history_mask |= point.mask
        tally.keep |= store.summaries.chunks(unit, held_mask)
        tally.other |= store.summaries.chunks(unit, history_mask)
    return dropped


def thin_unit(vault: "Vault", unit: str, max_points: int = K.MAX_POINTS_PER_UNIT, *,
              exported: Optional[Mapping[str, float]] = None) -> List[str]:
    """Drop a unit's oldest droppable points beyond ``max_points``. Output: the point ids dropped.

    Description: never the newest, never a pinned point, nothing at all from a protected unit (original gone, or export unknown; a conversation's export source stays:
      ``exported`` as :func:`protection` takes it). Lifecycle points (kill, remove, sleep, restart) outlive
      ``follow`` points of the same age.
    """
    if exported is None:
        newest, _at = _newest_of(vault.manifests, unit, vault.manifests.point_ids(unit))
        if newest is None:
            return []
        exported = exported_conversations([conversation_of(unit, newest)])
    return _walk_unit(vault, unit, exported, max_points, None)


def _history(vault: "Vault", tally: _Tally) -> Dict[str, int]:
    counts: Dict[str, int] = dict(tally.counts)
    counts["history_bytes"] = sum(vault.blobs.stored_size(h) for h in tally.other - tally.keep)
    counts["used_bytes"] = counts["history_bytes"] + sum(vault.blobs.stored_size(h) for h in tally.keep)
    return counts


_ASSESS_LOCK = threading.Lock()


def assess(vault: "Vault", cap_bytes: Union[int, Callable[[], int]] = K.DEFAULT_HISTORY_CAP_BYTES, *,
           now: Optional[float] = None, pace: Optional[Throttle] = None) -> Dict[str, Any]:
    with _ASSESS_LOCK:
        cap = cap_bytes() if callable(cap_bytes) else cap_bytes
        store = vault.manifests
        units = store.units()
        store.summaries.retain(units)
        newest = {unit: _newest_of(store, unit, store.point_ids(unit))[0] for unit in units}
        exported = exported_conversations(conversation_of(u, m) for u, m in newest.items() if m is not None)
        tally = _Tally(set(), set(), {"units": 0, "points": 0, "pinned": 0, "protected_units": 0})
        for unit in units:
            started = time.monotonic()
            _walk_unit(vault, unit, exported, K.MAX_POINTS_PER_UNIT, tally)
            if pace is not None:
                pace.rest(time.monotonic() - started)
        state = _history(vault, tally)
        state.update(cap_bytes=cap, over_cap=state["history_bytes"] > cap, checked_at=time.time() if now is None else now)
        if state["over_cap"]:
            logger.warning("vault_over_cap", history_bytes=state["history_bytes"], cap_bytes=cap,
                           note="new history points are paused; nothing is deleted. raise the cap or move the vault")
        write_state(vault.root, {**read_state(vault.root), **state})
        store.save_summaries()
        return state


def referenced_chunks(vault: "Vault") -> Set[str]:
    if not vault.manifests.exists():
        raise ManifestError("the manifests folder is missing")
    store = vault.manifests
    refs: Set[str] = set()
    units = store.units()
    store.summaries.retain(units)
    for unit in units:
        ids = store.point_ids(unit)
        store.summaries.prune(unit, ids)
        mask = 0
        for point_id in ids:
            mask |= store.summary(unit, point_id).mask
        refs |= store.summaries.chunks(unit, mask)
    store.save_summaries()
    return refs


def collect_garbage(vault: "Vault", *, grace: float = K.GC_GRACE_SECONDS, now: Optional[float] = None) -> Dict[str, int]:
    stamp = time.time() if now is None else now
    result = {"removed": 0, "bytes": 0, "kept": 0, "blob_bytes": 0}
    with vault.guard.try_exclusive() as held:
        if not held:
            return {**result, "busy": 1}
        try:
            refs = referenced_chunks(vault)
        except ManifestError as exc:
            logger.error("vault_gc_skipped_unreadable_manifest", error=str(exc))
            return {**result, "skipped": 1}
        blobs = list(vault.blobs.all_blobs())
        if blobs and not refs:
            logger.error("vault_gc_skipped_no_references", blobs=len(blobs),
                         note="blobs exist but no manifest names a chunk; the manifests may be missing, so nothing is removed")
            return {**result, "skipped": 1}
        for sha, path in blobs:
            try:
                st = path.stat()
            except OSError:
                continue
            if sha in refs or stamp - st.st_mtime < grace:
                result["kept"] += 1
                result["blob_bytes"] += st.st_size
                continue
            path.unlink(missing_ok=True)
            result["removed"] += 1
            result["bytes"] += st.st_size
        for temp in list(vault.blobs.temp_files()):
            try:
                if stamp - temp.stat().st_mtime >= grace:
                    temp.unlink(missing_ok=True)
            except OSError:
                continue
    if result["removed"]:
        logger.info("vault_chunks_collected", **result)
    write_state(vault.root, {**read_state(vault.root), "blob_bytes": result["blob_bytes"], "blob_count": result["kept"]})
    return result


def sole_copy_units(root: Path) -> int:
    from src.cplugs.save.vault.manifest import ManifestStore

    store = ManifestStore(root)
    return sum(1 for unit in store.units() if (newest := store.newest(unit)) is not None and original_gone(newest))
