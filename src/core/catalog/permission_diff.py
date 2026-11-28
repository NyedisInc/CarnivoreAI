
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from src.plugins.sdk._manifest_v2_sections import _parse_events, _parse_services
from src.plugins.sdk.manifest_v2 import (
    _READ_MAP,
    _WRITE_MAP,
    ManifestV2Error,
    has_v2_manifest,
    load_manifest_v2,
)
from src.plugins.sdk.network import PERMISSION_PREFIXES, WRITE_METHODS
from src.plugins.sdk.permission_registry import EVENTS_PREFIX, SERVICES_PREFIX

_READ_CANONICAL = frozenset(_READ_MAP.values())


@dataclass(frozen=True)
class CapabilitySnapshot:

    read: Tuple[str, ...] = ()
    write: Tuple[str, ...] = ()
    network: Tuple[str, ...] = ()
    secrets: Tuple[str, ...] = ()
    services_provides: Tuple[str, ...] = ()
    services_provides_methods: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    services_consumes: Tuple[str, ...] = ()
    events_on: Tuple[str, ...] = ()
    events_emit: Tuple[str, ...] = ()
    events_allowed: Tuple[str, ...] = ()
    ui_slots: Tuple[str, ...] = ()
    harnesses: Tuple[str, ...] = ()
    channels: Tuple[str, ...] = ()
    tier0: bool = True
    run_mode: str = ""
    run_cmd: Tuple[str, ...] = ()
    trust: str = "sandbox"
    parse_failed: bool = False


@dataclass(frozen=True)
class ExecutionEscalation:

    tier0_to_run: bool = False
    run_mode_changed: bool = False
    old_run_mode: str = ""
    new_run_mode: str = ""
    run_cmd_changed: bool = False
    old_run_cmd: Tuple[str, ...] = ()
    new_run_cmd: Tuple[str, ...] = ()
    trust_escalated: bool = False

    def any_escalation(self) -> bool:
        return bool(
            self.tier0_to_run
            or self.run_mode_changed
            or self.run_cmd_changed
            or self.trust_escalated
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tier0_to_run": self.tier0_to_run,
            "run_mode_changed": self.run_mode_changed,
            "old_run_mode": self.old_run_mode,
            "new_run_mode": self.new_run_mode,
            "run_cmd_changed": self.run_cmd_changed,
            "old_run_cmd": list(self.old_run_cmd),
            "new_run_cmd": list(self.new_run_cmd),
            "trust_escalated": self.trust_escalated,
        }


@dataclass(frozen=True)
class ProvenanceDiff:

    commit_sha_mismatch: bool = False
    repo_changed: bool = False
    old_repo: str = ""
    new_repo: str = ""
    old_tag: str = ""
    new_tag: str = ""
    old_commit_sha: str = ""
    new_commit_sha: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "commit_sha_mismatch": self.commit_sha_mismatch,
            "repo_changed": self.repo_changed,
            "old_repo": self.old_repo,
            "new_repo": self.new_repo,
            "old_tag": self.old_tag,
            "new_tag": self.new_tag,
            "old_commit_sha": self.old_commit_sha,
            "new_commit_sha": self.new_commit_sha,
        }


@dataclass(frozen=True)
class PermissionBucket:

    read: Tuple[str, ...] = ()
    write: Tuple[str, ...] = ()
    network: Tuple[str, ...] = ()
    secrets: Tuple[str, ...] = ()
    services_provides: Tuple[str, ...] = ()
    services_consumes: Tuple[str, ...] = ()
    events_on: Tuple[str, ...] = ()
    events_emit: Tuple[str, ...] = ()
    ui_slots: Tuple[str, ...] = ()
    harnesses: Tuple[str, ...] = ()
    channels: Tuple[str, ...] = ()

    def any_nonempty(self) -> bool:
        return bool(
            self.read
            or self.write
            or self.network
            or self.secrets
            or self.services_provides
            or self.services_consumes
            or self.events_on
            or self.events_emit
            or self.ui_slots
            or self.harnesses
            or self.channels
        )

    def as_dict(self) -> Dict[str, List[str]]:
        return {
            "read": list(self.read),
            "write": list(self.write),
            "network": list(self.network),
            "secrets": list(self.secrets),
            "services_provides": list(self.services_provides),
            "services_consumes": list(self.services_consumes),
            "events_on": list(self.events_on),
            "events_emit": list(self.events_emit),
            "ui_slots": list(self.ui_slots),
            "harnesses": list(self.harnesses),
            "channels": list(self.channels),
        }


@dataclass(frozen=True)
class PermissionDiff:

    requires_reconsent: bool
    added: PermissionBucket
    removed: PermissionBucket
    execution_escalation: ExecutionEscalation
    provenance: ProvenanceDiff

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requires_reconsent": self.requires_reconsent,
            "added": self.added.as_dict(),
            "removed": self.removed.as_dict(),
            "execution_escalation": self.execution_escalation.as_dict(),
            "provenance": self.provenance.as_dict(),
        }


def _classify_app_permissions(
    permissions: Iterable[str],
) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    reads: Set[str] = set()
    writes: Set[str] = set()
    services: Set[str] = set()
    events: Set[str] = set()
    for p in permissions:
        if not isinstance(p, str) or not p:
            continue
        if p.startswith(("net:", "net.write:", "lan:", "lan.write:", *PERMISSION_PREFIXES)):
            continue
        if p.startswith(SERVICES_PREFIX):
            tail = p[len(SERVICES_PREFIX) :]
            if tail:
                services.add(tail)
            continue
        if p.startswith(EVENTS_PREFIX):
            tail = p[len(EVENTS_PREFIX) :]
            if tail:
                events.add(tail)
            continue
        if p in _READ_CANONICAL or p.endswith(".read") or p.startswith("feed.view:"):
            reads.add(p)
        else:
            writes.add(p)
    return reads, writes, services, events


def _from_v2(v2: Any) -> CapabilitySnapshot:
    reads, writes, perm_services, perm_events = _classify_app_permissions(v2.permissions)
    net: Set[str] = set()
    for h in (getattr(v2.network, "network_hosts", None) or getattr(v2.network, "hosts", None) or ()):
        net.add(h.host)
        if any(m in WRITE_METHODS for m in (getattr(h, "methods", ()) or ())):
            net.add(f"{h.host}:write")
    for lh in getattr(v2.network, "lan_hosts", ()) or ():
        entry = getattr(lh, "entry", "")
        if entry:
            net.add(entry)
            if any(m in WRITE_METHODS for m in (getattr(lh, "methods", ()) or ())):
                net.add(f"{entry}:write")
    secrets = sorted({s.name for s in (getattr(v2.network, "secrets", ()) or ()) if getattr(s, "name", "")})

    provides_names: Set[str] = set()
    provides_methods: Dict[str, Tuple[str, ...]] = {}
    for svc in getattr(v2, "services_provides", ()) or ():
        if isinstance(svc, Mapping) and svc.get("name"):
            name = str(svc["name"])
            provides_names.add(name)
            methods = tuple(sorted(str(m) for m in (svc.get("methods") or ()) if m))
            provides_methods[name] = methods

    consumes = sorted({*(getattr(v2, "services_consumes", ()) or ()), *perm_services})
    ev_on = sorted({*(getattr(v2, "events_on", ()) or ()), *perm_events})
    ev_emit = sorted({*(getattr(v2, "events_emit", ()) or ())})
    ev_allowed = sorted({*(getattr(v2, "events_allowed", ()) or ())})
    ui_contrib = getattr(v2, "ui_contribute", None)
    ui_slots = sorted({str(k) for k in ui_contrib.keys() if k}) if isinstance(ui_contrib, Mapping) else []
    harnesses = sorted({str(h) for h in (getattr(v2, "harnesses", ()) or ()) if h})
    ch_map = getattr(v2, "channels", None)
    channels = sorted({str(k) for k in ch_map.keys() if k}) if isinstance(ch_map, Mapping) else []

    tier0 = bool(getattr(v2, "tier0", True))
    run_cmd = tuple(str(x) for x in (getattr(v2, "run_cmd", ()) or ())) if not tier0 else ()
    run_mode = str(getattr(v2, "run_mode", "rpc") or "rpc") if not tier0 else ""
    trust = str(getattr(v2, "trust", "") or "sandbox")
    return CapabilitySnapshot(
        read=tuple(sorted(reads)),
        write=tuple(sorted(writes)),
        network=tuple(sorted(net)),
        secrets=tuple(secrets),
        services_provides=tuple(sorted(provides_names)),
        services_provides_methods=provides_methods,
        services_consumes=tuple(consumes),
        events_on=tuple(ev_on),
        events_emit=tuple(ev_emit),
        events_allowed=tuple(ev_allowed),
        ui_slots=tuple(ui_slots),
        harnesses=tuple(harnesses),
        channels=tuple(channels),
        tier0=tier0,
        run_mode=run_mode,
        run_cmd=run_cmd,
        trust=trust,
    )


def _from_raw_doc(raw: Mapping[str, Any]) -> CapabilitySnapshot:
    reads: Set[str] = set()
    writes: Set[str] = set()
    net: Set[str] = set()
    secrets: Set[str] = set()
    svc_consumes: Set[str] = set()
    ev_on: Set[str] = set()
    ev_emit: Set[str] = set()
    ev_allowed: Set[str] = set()
    svc_provides: Set[str] = set()
    svc_methods: Dict[str, Tuple[str, ...]] = {}

    perms = raw.get("permissions")
    if isinstance(perms, Mapping):
        for r in perms.get("read") or ():
            if isinstance(r, str) and r:
                reads.add(_READ_MAP.get(r, r))
        for w in perms.get("write") or ():
            if isinstance(w, str) and w:
                writes.add(_WRITE_MAP.get(w, w))
        for item in perms.get("network") or ():
            if isinstance(item, str) and item:
                net.add(item)
            elif isinstance(item, Mapping) and item.get("host"):
                host = str(item["host"])
                net.add(host)
                methods = item.get("methods") or ()
                if any(str(m).upper() in WRITE_METHODS for m in methods):
                    net.add(f"{host}:write")
        for item in perms.get("lan") or ():
            if isinstance(item, str) and item:
                net.add(item)
            elif isinstance(item, Mapping) and item.get("host"):
                host = str(item["host"])
                net.add(host)
                methods = item.get("methods") or ()
                if any(str(m).upper() in WRITE_METHODS for m in methods):
                    net.add(f"{host}:write")
        for item in perms.get("secrets") or ():
            if isinstance(item, str) and item:
                secrets.add(item)
            elif isinstance(item, Mapping) and (item.get("key") or item.get("name")):
                secrets.add(str(item.get("key") or item.get("name")))
        for s in perms.get("services") or ():
            if isinstance(s, str) and s:
                svc_consumes.add(s)
        for e in perms.get("events") or ():
            if isinstance(e, str) and e:
                ev_on.add(e)
        r2, w2, s2, e2 = _classify_app_permissions(perms.get("app") or ())
        reads |= r2
        writes |= w2
        svc_consumes |= s2
        ev_on |= e2
    elif isinstance(perms, list):
        r2, w2, s2, e2 = _classify_app_permissions(perms)
        reads |= r2
        writes |= w2
        svc_consumes |= s2
        ev_on |= e2

    for h in raw.get("network_hosts") or ():
        if isinstance(h, str) and h:
            net.add(h)
        elif isinstance(h, Mapping) and h.get("host"):
            host = str(h["host"])
            net.add(host)
            methods = h.get("methods") or ()
            if any(str(m).upper() in WRITE_METHODS for m in methods):
                net.add(f"{host}:write")
    for lh in raw.get("lan_hosts") or ():
        if isinstance(lh, str) and lh:
            net.add(lh)
        elif isinstance(lh, Mapping) and lh.get("host"):
            host = str(lh["host"])
            net.add(host)
            methods = lh.get("methods") or ()
            if any(str(m).upper() in WRITE_METHODS for m in methods):
                net.add(f"{host}:write")
    for s in raw.get("secrets") or ():
        if isinstance(s, str) and s:
            secrets.add(s)
        elif isinstance(s, Mapping) and (s.get("key") or s.get("name")):
            secrets.add(str(s.get("key") or s.get("name")))

    if isinstance(raw.get("services"), Mapping):
        try:
            provides, consumes = _parse_services(raw.get("services"), "diff")
            for p in provides:
                if p.get("name"):
                    pname = str(p["name"])
                    svc_provides.add(pname)
                    svc_methods[pname] = tuple(sorted(str(m) for m in (p.get("methods") or ()) if m))
            svc_consumes |= set(consumes)
        except ManifestV2Error:
            pass
    if isinstance(raw.get("events"), Mapping):
        ev_raw = raw["events"]
        try:
            on_evs, emit_evs = _parse_events({k: v for k, v in ev_raw.items() if k in ("on", "emit")}, "diff")
            ev_on |= set(on_evs)
            ev_emit |= set(emit_evs)
        except ManifestV2Error:
            pass
        allowed_raw = ev_raw.get("allowed")
        if isinstance(allowed_raw, (list, tuple)):
            ev_allowed |= {str(x) for x in allowed_raw if isinstance(x, str) and x}

    ui_raw = raw.get("ui")
    contrib_raw = ui_raw.get("contribute") if isinstance(ui_raw, Mapping) else None
    ui_slots_set: Set[str] = (
        {str(k) for k in contrib_raw.keys() if isinstance(k, str) and k}
        if isinstance(contrib_raw, Mapping)
        else set()
    )
    harnesses_set: Set[str] = set()
    raw_harnesses = raw.get("harnesses")
    if isinstance(raw_harnesses, list):
        harnesses_set = {str(h) for h in raw_harnesses if isinstance(h, str) and h}
    elif isinstance(raw_harnesses, Mapping):
        if set(raw_harnesses) == {"files"} and isinstance(raw_harnesses.get("files"), list):
            harnesses_set = {str(h) for h in raw_harnesses["files"] if isinstance(h, str) and h}
        else:
            harnesses_set = {str(v) for v in raw_harnesses.values() if isinstance(v, str) and v}
    ch_raw = raw.get("channels")
    channels_set: Set[str] = (
        {str(k) for k in ch_raw.keys() if isinstance(k, str) and k}
        if isinstance(ch_raw, Mapping)
        else set()
    )

    run_blk = raw.get("run")
    if isinstance(run_blk, Mapping) and isinstance(run_blk.get("cmd"), list) and run_blk["cmd"]:
        tier0 = False
        run_cmd = tuple(str(x) for x in run_blk["cmd"])
        run_mode = str(run_blk.get("mode") or "rpc")
    elif raw.get("schema") != 2 and raw.get("entry"):
        tier0 = False
        run_cmd = (str(raw["entry"]),)
        run_mode = "rpc"
    else:
        tier0 = True
        run_cmd = ()
        run_mode = ""

    trust = str(raw.get("trust") or "sandbox")
    return CapabilitySnapshot(
        read=tuple(sorted(reads)),
        write=tuple(sorted(writes)),
        network=tuple(sorted(net)),
        secrets=tuple(sorted(secrets)),
        services_provides=tuple(sorted(svc_provides)),
        services_provides_methods=svc_methods,
        services_consumes=tuple(sorted(svc_consumes)),
        events_on=tuple(sorted(ev_on)),
        events_emit=tuple(sorted(ev_emit)),
        events_allowed=tuple(sorted(ev_allowed)),
        ui_slots=tuple(sorted(ui_slots_set)),
        harnesses=tuple(sorted(harnesses_set)),
        channels=tuple(sorted(channels_set)),
        tier0=tier0,
        run_mode=run_mode,
        run_cmd=run_cmd,
        trust=trust,
    )


def extract_capabilities(folder: Optional[Path]) -> CapabilitySnapshot:
    if folder is None or not Path(folder).is_dir():
        return CapabilitySnapshot()
    root = Path(folder)
    if has_v2_manifest(root):
        try:
            v2 = load_manifest_v2(root, expected_id=None, expected_tier=None, allow_tier_override=True)
            return _from_v2(v2)
        except (ManifestV2Error, OSError, ValueError):
            for fname, loader in (("carnivore.toml", tomllib.loads), ("carnivore.json", json.loads)):
                fpath = root / fname
                if fpath.is_file():
                    try:
                        raw = loader(fpath.read_text(encoding="utf-8"))
                        if isinstance(raw, Mapping):
                            return _from_raw_doc(raw)
                    except (OSError, ValueError, tomllib.TOMLDecodeError):
                        return CapabilitySnapshot(parse_failed=True)
            return CapabilitySnapshot(parse_failed=True)

    for fname in ("carnivore.json", "cplug.json"):
        fpath = root / fname
        if fpath.is_file():
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(raw, Mapping):
                    return _from_raw_doc(raw)
            except (OSError, ValueError):
                return CapabilitySnapshot(parse_failed=True)
    return CapabilitySnapshot()


def _bucket_diff(old: CapabilitySnapshot, new: CapabilitySnapshot) -> Tuple[PermissionBucket, PermissionBucket]:
    def _added(a: Tuple[str, ...], b: Tuple[str, ...]) -> Tuple[str, ...]:
        return tuple(sorted(set(b) - set(a)))

    added = PermissionBucket(
        read=_added(old.read, new.read),
        write=_added(old.write, new.write),
        network=_added(old.network, new.network),
        secrets=_added(old.secrets, new.secrets),
        services_provides=_added(old.services_provides, new.services_provides),
        services_consumes=_added(old.services_consumes, new.services_consumes),
        events_on=_added(old.events_on, new.events_on),
        events_emit=_added(old.events_emit, new.events_emit),
        ui_slots=_added(old.ui_slots, new.ui_slots),
        harnesses=_added(old.harnesses, new.harnesses),
        channels=_added(old.channels, new.channels),
    )
    removed = PermissionBucket(
        read=_added(new.read, old.read),
        write=_added(new.write, old.write),
        network=_added(new.network, old.network),
        secrets=_added(new.secrets, old.secrets),
        services_provides=_added(new.services_provides, old.services_provides),
        services_consumes=_added(new.services_consumes, old.services_consumes),
        events_on=_added(new.events_on, old.events_on),
        events_emit=_added(new.events_emit, old.events_emit),
        ui_slots=_added(new.ui_slots, old.ui_slots),
        harnesses=_added(new.harnesses, old.harnesses),
        channels=_added(new.channels, old.channels),
    )
    return added, removed


def compute_permission_diff(
    installed_dir: Optional[Path],
    staged_dir: Optional[Path],
    *,
    row: Any = None,
    version: Any = None,
) -> PermissionDiff:
    old_caps = extract_capabilities(installed_dir)
    new_caps = extract_capabilities(staged_dir)

    added, removed = _bucket_diff(old_caps, new_caps)

    tier0_to_run = old_caps.tier0 and (not new_caps.tier0)
    run_mode_changed = (not old_caps.tier0) and (not new_caps.tier0) and (old_caps.run_mode != new_caps.run_mode)
    run_cmd_changed = (not old_caps.tier0) and (not new_caps.tier0) and (old_caps.run_cmd != new_caps.run_cmd)
    trust_escalated = (old_caps.trust or "sandbox") != "unrestricted" and new_caps.trust == "unrestricted"
    exec_esc = ExecutionEscalation(
        tier0_to_run=tier0_to_run,
        run_mode_changed=run_mode_changed,
        old_run_mode=old_caps.run_mode,
        new_run_mode=new_caps.run_mode,
        run_cmd_changed=run_cmd_changed,
        old_run_cmd=old_caps.run_cmd,
        new_run_cmd=new_caps.run_cmd,
        trust_escalated=trust_escalated,
    )

    prov_obj = getattr(version, "provenance", None)
    old_repo = str(getattr(row, "provenance_repo", "") or "")
    new_repo = str(getattr(prov_obj, "repo", "") or "") if prov_obj is not None else ""
    old_tag = str(getattr(row, "provenance_tag", "") or "")
    new_tag = str(getattr(prov_obj, "tag", "") or "") if prov_obj is not None else ""
    old_sha = str(getattr(row, "commit_sha", "") or "")
    new_sha = str(getattr(prov_obj, "commit_sha", "") or "") if prov_obj is not None else ""

    repo_changed = bool(old_repo and new_repo and old_repo.lower() != new_repo.lower())
    old_ver = str(getattr(row, "version", "") or "")
    new_ver = str(getattr(version, "v", "") or "")
    same_version_or_tag = bool(
        (old_ver and new_ver and old_ver == new_ver)
        or (old_tag and new_tag and old_tag == new_tag)
    )
    commit_sha_mismatch = bool(
        old_sha and new_sha and old_sha != new_sha and same_version_or_tag
    )
    prov_diff = ProvenanceDiff(
        commit_sha_mismatch=commit_sha_mismatch,
        repo_changed=repo_changed,
        old_repo=old_repo,
        new_repo=new_repo,
        old_tag=old_tag,
        new_tag=new_tag,
        old_commit_sha=old_sha,
        new_commit_sha=new_sha,
    )

    service_methods_widened = any(
        bool(set(new_caps.services_provides_methods.get(svc, ())) - set(old_caps.services_provides_methods.get(svc, ())))
        for svc in new_caps.services_provides
        if svc in old_caps.services_provides
    )
    events_allowed_widened = bool(set(new_caps.events_allowed) - set(old_caps.events_allowed))

    requires_reconsent = bool(
        added.any_nonempty()
        or service_methods_widened
        or events_allowed_widened
        or exec_esc.any_escalation()
        or repo_changed
        or commit_sha_mismatch
        or old_caps.parse_failed
        or new_caps.parse_failed
    )
    return PermissionDiff(
        requires_reconsent=requires_reconsent,
        added=added,
        removed=removed,
        execution_escalation=exec_esc,
        provenance=prov_diff,
    )
