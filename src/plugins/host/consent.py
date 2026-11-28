
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.plugins.host import risk
from src.plugins.sdk import permission_registry as registry
from src.plugins.sdk.manifest import Manifest


class ConsentRefused(Exception):

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def grants_sha(grants: Iterable[str]) -> str:
    return _sha(sorted(set(grants)))


def reason_for(manifest: Manifest, permission: str) -> str:
    if permission in manifest.permission_reasons:
        return manifest.permission_reasons[permission]
    for entry in (*manifest.network.network_hosts, *manifest.network.lan_hosts):
        if permission in (entry.permission, entry.write_permission):
            return entry.reason
    return ""


def rows(manifest: Manifest, granted: Sequence[str] = ()) -> List[Dict[str, Any]]:
    out = []
    for name in manifest.permissions:
        level = registry.risk_of(name, manifest.tier)
        out.append({"name": name, "risk": level, "reason": reason_for(manifest, name), "granted": name in granted,
                    "needs_tick": risk.needs_tick(level)})
    return out


def warnings_of(manifest: Manifest) -> List[Dict[str, Any]]:
    found = risk.warnings_for(manifest.permissions)
    return [*found, {"code": "unrestricted"}] if getattr(manifest, "trust", "") == "unrestricted" else found


def declared_ui_slots(manifest: Any) -> Tuple[str, ...]:
    contribute = getattr(manifest, "ui_contribute", None)
    if not isinstance(contribute, Mapping):
        return ()
    return tuple(str(k) for k in contribute.keys())


def ui_slot_rows(manifest: Any, granted_slots: Sequence[str] = ()) -> List[Dict[str, Any]]:
    contribute = getattr(manifest, "ui_contribute", None)
    if not isinstance(contribute, Mapping):
        return []
    out: List[Dict[str, Any]] = []
    for slot, entries in contribute.items():
        slot_name = str(slot)
        count = len(entries) if isinstance(entries, (list, tuple)) else 1
        reason = reason_for(manifest, f"ui.slot:{slot_name}") or reason_for(manifest, slot_name)
        out.append({
            "slot": slot_name,
            "count": count,
            "risk": registry.MEDIUM,
            "reason": reason,
            "granted": slot_name in granted_slots,
            "needs_tick": True,
        })
    return out


def sheet(manifest: Manifest, granted: Sequence[str] = (), granted_slots: Sequence[str] = ()) -> Dict[str, Any]:
    perms = rows(manifest, granted)
    slot_rows = ui_slot_rows(manifest, granted_slots)
    warnings = warnings_of(manifest)
    shown = [{k: p[k] for k in ("name", "risk", "reason")} for p in perms]
    body_doc: Dict[str, Any] = {"id": manifest.id, "version": manifest.version, "permissions": shown, "warnings": warnings}
    if slot_rows:
        body_doc["ui_slots"] = [{k: s[k] for k in ("slot", "count", "risk", "reason")} for s in slot_rows]
    body = _sha(body_doc)
    return {"id": manifest.id, "version": manifest.version, "tier": manifest.tier,
            "consent_required": risk.needs_consent(manifest.tier), "digest": manifest.code_digest, "body_sha": body,
            "permissions": perms, "ui_slots": slot_rows, "warnings": warnings,
            "grants_sha": grants_sha(manifest.permissions), "ui_slots_sha": grants_sha(declared_ui_slots(manifest))}


def check(
    manifest: Manifest,
    requested: Sequence[str],
    current: Sequence[str],
    consent: Optional[Mapping[str, Any]],
    *,
    requested_slots: Optional[Sequence[str]] = None,
    current_slots: Sequence[str] = (),
) -> Tuple[str, ...]:
    levels = {p: registry.risk_of(p, manifest.tier) for p in requested}
    never = sorted(p for p, level in levels.items() if level == registry.NEVER)
    if never:
        raise ConsentRefused(422, "grant_never", f"{manifest.id} cannot be granted {', '.join(never)}")
    if requested_slots is not None:
        declared = set(declared_ui_slots(manifest))
        unknown_slots = sorted(s for s in requested_slots if s not in declared)
        if unknown_slots:
            raise ConsentRefused(422, "grant_not_asked", f"{manifest.id} did not ask for ui slots {', '.join(unknown_slots)}")
    if risk.needs_consent(manifest.tier) and not manifest.code_digest:
        raise ConsentRefused(409, "digest_unknown", f"{manifest.id} carries no code digest, so its code cannot be confirmed")
    if not isinstance(consent, Mapping):
        raise ConsentRefused(422, "consent_required", f"{manifest.id}: send the consent body from GET /cplugs/{manifest.id}/sheet")
    shown = sheet(manifest, current, current_slots)
    if consent.get("digest") != shown["digest"] or consent.get("body_sha") != shown["body_sha"]:
        raise ConsentRefused(409, "consent_stale", f"{manifest.id} changed since the sheet was shown; read it again")
    if consent.get("grants_sha") != grants_sha(requested):
        raise ConsentRefused(422, "consent_mismatch", "the consent was given for a different set of grants")
    if requested_slots is not None and consent.get("ui_slots_sha") != grants_sha(requested_slots):
        raise ConsentRefused(422, "consent_mismatch", "the consent was given for a different set of ui slots")
    unexplained = sorted(p for p in requested if not reason_for(manifest, p))
    if unexplained:
        raise ConsentRefused(422, "reason_missing", f"{manifest.id} gives no reason for {', '.join(unexplained)}")
    if requested_slots is not None:
        unexplained_slots = sorted(s for s in requested_slots if not (reason_for(manifest, f"ui.slot:{s}") or reason_for(manifest, s)))
        if unexplained_slots:
            raise ConsentRefused(422, "reason_missing", f"{manifest.id} gives no reason for ui slots {', '.join(unexplained_slots)}")
    ticks = consent.get("ticks")
    ticked = set(ticks) if isinstance(ticks, list) and all(isinstance(t, str) for t in ticks) else set()
    fresh = tuple(p for p in requested if p not in current)
    missing = sorted(p for p in fresh if risk.needs_tick(levels[p]) and p not in ticked)
    if missing:
        raise ConsentRefused(422, "tick_missing", f"tick each of: {', '.join(missing)}")
    if requested_slots is not None:
        raw_slot_ticks = consent.get("slot_ticks")
        slot_ticked = set(raw_slot_ticks) if isinstance(raw_slot_ticks, list) and all(isinstance(t, str) for t in raw_slot_ticks) else set()
        fresh_slots = [s for s in requested_slots if s not in current_slots]
        missing_slots = sorted(s for s in fresh_slots if s not in slot_ticked and f"ui.slot:{s}" not in ticked)
        if missing_slots:
            raise ConsentRefused(422, "tick_missing", f"tick each ui slot: {', '.join(missing_slots)}")
    return tuple(p for p in fresh if risk.needs_tick(levels[p]))
