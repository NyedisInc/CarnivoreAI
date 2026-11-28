
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

import structlog

from src.plugins.save.engine import layout
from src.plugins.save.vault import constants as K
from src.plugins.save.offload import ledger as offload_ledger
from src.plugins.save.vault import gone_watch
from src.plugins.save.vault.manifest import Manifest, ManifestError, ManifestStore
from src.plugins.save.vault.summary import PointSummary, probe_of
from src.plugins.sdk import exports as sx
from src.plugins.sdk import transcript_files as tf
from src.plugins.sdk.blob_codec import Throttle

if TYPE_CHECKING:  # pragma: no cover
    from src.plugins.save.vault.store import Vault

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


PROTECT_OFFLOADED: str = "offloaded"
PROTECT_OFFLOAD_UNKNOWN: str = "offload_unknown"


def protection(vault: "Vault", unit: str, newest: Union[Manifest, PointSummary],
               exported: Optional[Mapping[str, float]] = None, offloaded: Optional[offload_ledger.OffloadedUnits] = None) -> Optional[str]:
    conversation = conversation_of(unit, newest)
    if offloaded is None:
        offloaded = offload_ledger.offloaded_units(vault.root, state_dir=Path(tf.state_dir()))
    if offloaded.holds(unit):
        return PROTECT_OFFLOAD_UNKNOWN if offloaded.unreadable else PROTECT_OFFLOADED
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
    if unit in _LAST_PROTECTION and _LAST_PROTECTION[unit] == reason:
        return
    _LAST_PROTECTION[unit] = reason
    if reason is not None:
        logger.info("vault_unit_protected", unit=unit, reason=reason, points=points)


def is_frozen(vault: "Vault") -> bool:
    return gone_watch.frozen(vault.root) is not None


def _drop(vault: "Vault", unit: str, points: List[PointSummary], max_points: int, *, one_copy: bool = False,
          spare: Optional[str] = None, mark_dirty: bool = True) -> List[str]:
    if len(points) <= (1 if one_copy else max_points):
        return []
    if is_frozen(vault):
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
        vault.changed(mark_dirty=mark_dirty)
    return dropped


@dataclass
class _Tally:

    keep: Set[str]
    other: Set[str]
    counts: Dict[str, int]
    gone: Dict[str, str] = field(default_factory=dict)
    from_disk: Set[str] = field(default_factory=set)


def _walk_unit(vault: "Vault", unit: str, exported: Mapping[str, float], max_points: int, tally: Optional[_Tally],
               offloaded: Optional[offload_ledger.OffloadedUnits] = None) -> List[str]:
    store = vault.manifests
    ids = store.point_ids(unit)
    store.summaries.prune(unit, ids)
    newest, newest_at = _newest_of(store, unit, ids)
    if newest is None:
        return []
    reason = protection(vault, unit, newest, exported, offloaded)
    whole = reason is not None
    _note_protection(unit, reason, len(ids))
    gone = reason == "original_gone" or (reason in (PROTECT_OFFLOADED, PROTECT_OFFLOAD_UNKNOWN) and original_gone(newest))
    if tally is not None and gone:
        probe = probe_of(newest)
        tally.gone[unit] = os.path.dirname(probe[0]) if probe else ""
    survivors = [p for p in (_summary_logged(store, unit, pid) for pid in ids[:newest_at]) if p is not None] + [newest]
    if tally is not None and any(p.reason not in K.REASONS_NOT_FROM_DISK for p in survivors):
        tally.from_disk.add(unit)
    at = export_time(vault, unit, newest, exported) if newest.conversation_id and not whole else None
    source = export_source(survivors, at) if at is not None else None
    dropped: List[str] = []
    if not whole:
        dropped = _drop(vault, unit, survivors, max_points, one_copy=bool(newest.conversation_id), spare=source,
                        mark_dirty=(tally is None))
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


def _moved_units(gone: Mapping[str, str], moved_folders: Sequence[str]) -> Set[str]:
    return {unit for unit, folder in gone.items()
            if any(folder == moved or folder.startswith(moved.rstrip("/") + "/") for moved in moved_folders)}


def assess(vault: "Vault", cap_bytes: Union[int, Callable[[], int]] = K.DEFAULT_HISTORY_CAP_BYTES, *,
           now: Optional[float] = None, pace: Optional[Throttle] = None, moved_folders: Sequence[str] = ()) -> Dict[str, Any]:
    with _ASSESS_LOCK:
        seq = vault.change_seq() if hasattr(vault, "change_seq") else None
        cap = cap_bytes() if callable(cap_bytes) else cap_bytes
        store = vault.manifests
        units = store.units()
        store.summaries.retain(units)
        newest = {unit: _newest_of(store, unit, store.point_ids(unit))[0] for unit in units}
        exported = exported_conversations(conversation_of(u, m) for u, m in newest.items() if m is not None)
        tally = _Tally(set(), set(), {"units": 0, "points": 0, "pinned": 0, "protected_units": 0})
        offloaded = offload_ledger.offloaded_units(vault.root, state_dir=Path(tf.state_dir()))
        for unit in units:
            started = time.monotonic()
            _walk_unit(vault, unit, exported, K.MAX_POINTS_PER_UNIT, tally, offloaded)
            if pace is not None:
                pace.rest(time.monotonic() - started)
        state = _history(vault, tally)
        state["mass_gone"] = gone_watch.observe(vault.root, tally.gone, time.time() if now is None else now,
                                                   intentional=_moved_units(tally.gone, moved_folders) | offload_ledger.intentional_units(vault.root),
                                                   seen_on_disk=tally.from_disk)
        state.update(cap_bytes=cap, over_cap=state["history_bytes"] > cap, checked_at=time.time() if now is None else now)
        if state["over_cap"]:
            logger.warning("vault_over_cap", history_bytes=state["history_bytes"], cap_bytes=cap,
                           note="new history points are paused; nothing is deleted. raise the cap or move the vault")
        write_state(vault.root, {**read_state(vault.root), **state})
        store.save_summaries()
        if seq is not None and hasattr(vault, "mark_assessed"):
            vault.mark_assessed(seq)
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
    if is_frozen(vault):
        logger.error("vault_gc_skipped_frozen", note="a mass-gone freeze is in force; nothing is collected until the owner clears it")
        return {**result, "skipped": 1}
    with vault.guard.try_exclusive() as held:
        if not held:
            return {**result, "busy": 1}
        try:
            refs = referenced_chunks(vault)
        except ManifestError as exc:
            logger.error("vault_gc_skipped_unreadable_manifest", error=str(exc), error_type=type(exc).__name__)
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
            vault.blobs.remove(sha, path=path)
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
    from src.plugins.save.vault.manifest import ManifestStore

    store = ManifestStore(root)
    return sum(1 for unit in store.units() if (newest := store.newest(unit)) is not None and original_gone(newest))
