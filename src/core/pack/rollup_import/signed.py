
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.pack.machines.settings_sign import Signing, signature_from
from src.core.pack.meshdata import envelope
from src.core.pack.rollup_import import relay_store, store

logger = structlog.get_logger()

NAMES_KEY = "names"
Proof = Tuple[int, str, int]
Verified = Dict[Tuple[str, str, int], Proof]


def group_key(conversation_id: str, hour: int) -> str:
    return f"{conversation_id}|{hour}"


def _epoch(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 62 else None


def group_body(provider: Optional[str], kind: Optional[str], name: Optional[str], usage: List[Any], counters: List[Any], epoch: int) -> Optional[Dict[str, Any]]:
    rows_u = sorted([list(r[:9]) for r in usage], key=lambda r: (r[0], r[1]))
    rows_c = sorted([list(r[:5]) for r in counters], key=lambda r: (r[0], r[1], r[2], r[3]))
    if len({(r[0], r[1]) for r in rows_u}) != len(rows_u) or len({tuple(r[:4]) for r in rows_c}) != len(rows_c):
        return None
    held = bool(rows_u or rows_c)
    return {"p": provider if held else None, "ak": kind if held else None, "an": name if rows_u else None, "u": rows_u, "c": rows_c, "e": epoch}


def wire_body(group: Any, epoch: Optional[int] = None) -> Optional[Tuple[str, int, Dict[str, Any]]]:
    norm = store.normalized(group)
    epoch = (_epoch(group.get("epoch")) if isinstance(group, dict) else None) if epoch is None else epoch
    if norm is None or epoch is None:
        return None
    cid, hour, provider, kind, name, usage, counters = norm
    body = group_body(provider, kind, name, usage, counters, epoch)
    return None if body is None else (cid, hour, body)


def sign_own_groups(groups: Iterable[Dict[str, Any]], signing: Signing, epoch: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    dropped = 0
    for group in groups:
        parsed = wire_body(group, epoch)
        rev = group.get("rev")
        sig = envelope.try_sign(envelope.KIND_ROLLUP, group_key(parsed[0], parsed[1]), rev, envelope.body_hash(parsed[2]), signing) \
            if parsed is not None and isinstance(rev, int) and not isinstance(rev, bool) else None
        if sig is None:
            dropped += 1
            continue
        out.append({**group, "epoch": epoch, "sig": sig.to_dict()})
    if dropped:
        logger.warning("pack_rollup_groups_unsigned", dropped=dropped)
    return out


def verify_groups(groups: Iterable[Any], origin_of: Callable[[Dict[str, Any]], str], lst: Any, *, relay: bool) -> Optional[Verified]:
    out: Verified = {}
    for group in groups:
        parsed = wire_body(group) if isinstance(group, dict) else None
        stamp = group.get("orev" if relay else "rev") if isinstance(group, dict) else None
        sig = signature_from(group.get("sig")) if isinstance(group, dict) else None
        if parsed is None or sig is None or not isinstance(stamp, int) or isinstance(stamp, bool) or stamp < 0:
            return None
        origin = origin_of(group)
        if not envelope.verify(envelope.KIND_ROLLUP, origin, group_key(parsed[0], parsed[1]), stamp, envelope.body_hash(parsed[2]), sig, lst):
            return None
        key = (origin, parsed[0], parsed[1])
        if key in out:
            return None
        out[key] = (stamp, sig.sig, parsed[2]["e"])
    return out


def names_body(names: Dict[str, str], homes: Dict[str, str], epoch: int) -> Dict[str, Any]:
    return {"n": names, "h": homes, "e": epoch}


def sign_names(names: Any, homes: Any, stamp: int, signing: Signing, epoch: int) -> Optional[Dict[str, Any]]:
    kept, hints = relay_store.clean_names(names, homes)
    sig = envelope.try_sign(envelope.KIND_ROLLUP_NAMES, NAMES_KEY, stamp, envelope.body_hash(names_body(kept, hints, epoch)), signing)
    return None if sig is None else {"project_names": kept, "project_homes": hints, "names_epoch": epoch, "names_sig": sig.to_dict()}


def verify_names(origin: str, names: Any, homes: Any, stamp: Any, sig_raw: Any, lst: Any, epoch: Any) -> Optional[Proof]:
    sig = signature_from(sig_raw)
    epoch = _epoch(epoch)
    if sig is None or epoch is None or not isinstance(stamp, int) or isinstance(stamp, bool) or stamp < 0 or not isinstance(names, dict) or not isinstance(homes, dict):
        return None
    kept, hints = relay_store.clean_names(names, homes)
    if kept != names or hints != homes:
        return None
    if not envelope.verify(envelope.KIND_ROLLUP_NAMES, origin, NAMES_KEY, stamp, envelope.body_hash(names_body(kept, hints, epoch)), sig, lst):
        return None
    return stamp, sig.sig, epoch
