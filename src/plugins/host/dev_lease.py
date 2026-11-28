
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

from src.plugins.host.permission_renames import current_names

DEFAULT_TTL_SECONDS = 60.0
MIN_TTL_SECONDS = 5.0
MAX_TTL_SECONDS = 300.0


def _paths_covered(base_paths: Tuple[str, ...], cand_paths: Tuple[str, ...]) -> bool:
    if not cand_paths:
        return base_paths == ("/",)
    if not base_paths:
        return False
    for cp in cand_paths:
        covered = False
        for bp in base_paths:
            if bp == "/" or cp == bp or cp.startswith(bp.rstrip("/") + "/"):
                covered = True
                break
        if not covered:
            return False
    return True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _step_sigs(steps: Any) -> Tuple[Tuple[str, str], ...]:
    if not isinstance(steps, (list, tuple)):
        return ()
    out: List[Tuple[str, str]] = []
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        action = str(step.get("action") or step.get("method") or "")
        params = step.get("params")
        out.append((action, _canonical_json(params if isinstance(params, Mapping) else {})))
    return tuple(out)


@dataclass(frozen=True)
class CapabilityBaseline:

    permissions: FrozenSet[str]
    network_hosts: Mapping[str, Tuple[FrozenSet[str], Tuple[str, ...], str]]
    lan_hosts: Mapping[str, Tuple[FrozenSet[str], Tuple[str, ...]]]
    secrets: FrozenSet[str]
    trust: str
    services_consumes: FrozenSet[str]
    services_provides: Mapping[str, FrozenSet[str]]
    events_emit: FrozenSet[str]
    events_allowed: FrozenSet[str]
    subscriptions: FrozenSet[str]
    tools: FrozenSet[Tuple[str, str]]
    webhooks: FrozenSet[Tuple[str, str, str]]
    channels: FrozenSet[Tuple[str, str, str, Tuple[Tuple[str, str], ...], str]]
    macros: FrozenSet[Tuple[str, Tuple[Tuple[str, str], ...]]]
    command_macros: FrozenSet[Tuple[str, Tuple[Tuple[str, str], ...]]]
    harnesses: FrozenSet[str]
    ai_features: Mapping[str, Tuple[str, int, int]]
    tier0: bool = False
    run_mode: str = "rpc"
    run_cmd: Tuple[str, ...] = ()
    routes: FrozenSet[str] = frozenset()
    timers: Mapping[str, int] = None  # type: ignore[assignment]
    views: Mapping[str, Tuple[FrozenSet[str], FrozenSet[str]]] = None  # type: ignore[assignment]
    topics: FrozenSet[str] = frozenset()
    data: FrozenSet[Tuple[str, str, str, str, str, str, str, str]] = frozenset()
    owns_files: FrozenSet[str] = frozenset()
    ui_contribute_slots: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if self.timers is None:
            object.__setattr__(self, "timers", {})
        if self.views is None:
            object.__setattr__(self, "views", {})

    def canonical_sha(self) -> str:
        doc = {
            "permissions": sorted(self.permissions),
            "network_hosts": {
                k: [sorted(v[0]), list(v[1]), v[2]] for k, v in sorted(self.network_hosts.items())
            },
            "lan_hosts": {k: [sorted(v[0]), list(v[1])] for k, v in sorted(self.lan_hosts.items())},
            "secrets": sorted(self.secrets),
            "trust": self.trust,
            "services_consumes": sorted(self.services_consumes),
            "services_provides": {k: sorted(v) for k, v in sorted(self.services_provides.items())},
            "events_emit": sorted(self.events_emit),
            "events_allowed": sorted(self.events_allowed),
            "subscriptions": sorted(self.subscriptions),
            "tools": [list(t) for t in sorted(self.tools)],
            "webhooks": [list(w) for w in sorted(self.webhooks)],
            "channels": [
                [name, method, url, [list(h) for h in hdrs], body]
                for name, method, url, hdrs, body in sorted(self.channels)
            ],
            "macros": [
                [k, [list(st) for st in steps]] for k, steps in sorted(self.macros)
            ],
            "command_macros": [
                [k, [list(st) for st in steps]] for k, steps in sorted(self.command_macros)
            ],
            "harnesses": sorted(self.harnesses),
            "ai_features": {k: list(v) for k, v in sorted(self.ai_features.items())},
            "tier0": self.tier0,
            "run_mode": self.run_mode,
            "run_cmd": list(self.run_cmd),
            "routes": sorted(self.routes),
            "timers": sorted(self.timers.items()),
            "views": {
                k: [sorted(v[0]), sorted(v[1])] for k, v in sorted(self.views.items())
            },
            "topics": sorted(self.topics),
            "data": [list(d) for d in sorted(self.data)],
            "owns_files": sorted(self.owns_files),
            "ui_contribute_slots": sorted(self.ui_contribute_slots),
        }
        return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def extract_baseline(manifest: Any) -> CapabilityBaseline:
    perms = frozenset(current_names(str(p) for p in (getattr(manifest, "permissions", ()) or ())))
    net = getattr(manifest, "network", None)
    net_hosts: Dict[str, Tuple[FrozenSet[str], Tuple[str, ...], str]] = {}
    lan_hosts: Dict[str, Tuple[FrozenSet[str], Tuple[str, ...]]] = {}
    secrets_set: set[str] = set()
    if net is not None:
        for h in getattr(net, "network_hosts", ()) or ():
            auth = getattr(h, "auth", None)
            auth_sig = f"{auth.secret}:{auth.header}:{auth.scheme}" if auth is not None else ""
            net_hosts[h.host] = (frozenset(h.methods), tuple(h.paths), auth_sig)
        for lh in getattr(net, "lan_hosts", ()) or ():
            lan_hosts[lh.entry] = (frozenset(lh.methods), tuple(lh.paths))
        for s in getattr(net, "secrets", ()) or ():
            secrets_set.add(str(s.name))

    subs = frozenset(
        str(s)
        for s in (
            *(getattr(manifest, "subscriptions", ()) or ()),
            *(getattr(manifest, "events_on", ()) or ()),
        )
    )
    events_allowed = frozenset(str(e) for e in (getattr(manifest, "events_allowed", ()) or ()))

    svc_prov_acc: Dict[str, set[str]] = {}
    for item in getattr(manifest, "services_provides", ()) or ():
        if isinstance(item, Mapping):
            sname = str(item.get("name", "") or "")
            methods = item.get("methods", ()) or ()
        else:
            sname = str(getattr(item, "name", "") or "")
            methods = getattr(item, "methods", ()) or ()
        if sname:
            svc_prov_acc.setdefault(sname, set()).update(str(m) for m in methods)
    services_provides = {k: frozenset(v) for k, v in svc_prov_acc.items()}

    tools = frozenset(
        (str(t.get("name", "")), str(t.get("gate", "read")))
        for t in (getattr(manifest, "tools", ()) or ())
        if isinstance(t, Mapping)
    )
    raw_webhooks = getattr(manifest, "webhooks", {}) or {}
    webhooks = frozenset(
        (str(k), str(v.get("hmac_secret", "")), str(v.get("header", "")))
        for k, v in (raw_webhooks.items() if isinstance(raw_webhooks, Mapping) else ())
        if isinstance(v, Mapping)
    )

    raw_channels = getattr(manifest, "channels", {}) or {}
    channel_sigs: set[Tuple[str, str, str, Tuple[Tuple[str, str], ...], str]] = set()
    if isinstance(raw_channels, Mapping):
        for k, v in raw_channels.items():
            if isinstance(v, Mapping):
                method = str(v.get("method", "POST") or "POST").upper()
                url = str(v.get("url", "") or "")
                raw_hdrs = v.get("headers") or {}
                hdrs = (
                    tuple(sorted((str(hk), str(hv)) for hk, hv in raw_hdrs.items()))
                    if isinstance(raw_hdrs, Mapping)
                    else ()
                )
                raw_body = v.get("body_template", "")
                body_tpl = _canonical_json(raw_body) if isinstance(raw_body, (dict, list)) else str(raw_body or "")
            else:
                method, url, hdrs, body_tpl = "POST", "", (), ""
            channel_sigs.add((str(k), method, url, hdrs, body_tpl))
    channels = frozenset(channel_sigs)

    raw_macros = getattr(manifest, "macros", {}) or {}
    macros = frozenset(
        (str(k), _step_sigs(v.get("steps", ()) if isinstance(v, Mapping) else ()))
        for k, v in (raw_macros.items() if isinstance(raw_macros, Mapping) else ())
    )

    ui_meta = getattr(manifest, "ui_meta", {}) or {}
    raw_cmds = ui_meta.get("commands", ()) if isinstance(ui_meta, Mapping) else ()
    command_macros = frozenset(
        (str(cmd.get("id", "")), _step_sigs(cmd.get("steps")))
        for cmd in (raw_cmds if isinstance(raw_cmds, (list, tuple)) else ())
        if isinstance(cmd, Mapping) and "steps" in cmd
    )

    harnesses = frozenset(str(h) for h in (getattr(manifest, "harnesses", ()) or ()))

    raw_ai = getattr(manifest, "ai_features", {}) or {}
    ai_features: Dict[str, Tuple[str, int, int]] = {}
    if isinstance(raw_ai, Mapping):
        for k, f in raw_ai.items():
            if isinstance(f, Mapping):
                cap = str(f.get("capability", "") or "")
                calls = int(f.get("calls_per_day", 0) or 0)
                toks = int(f.get("tokens_per_day", f.get("max_tokens", 0)) or 0)
            else:
                cap = str(getattr(f, "capability", "") or "")
                calls = int(getattr(f, "calls_per_day", 0) or 0)
                toks = int((getattr(f, "tokens_per_day", 0) or getattr(f, "max_tokens", 0)) or 0)
            ai_features[str(k)] = (cap, calls, toks)

    raw_timers = getattr(manifest, "timers", {}) or {}
    timers = (
        {str(k): int(v) for k, v in raw_timers.items()}
        if isinstance(raw_timers, Mapping)
        else {}
    )
    raw_views = getattr(manifest, "views", ()) or ()
    views = {
        str(v["name"]): (
            frozenset(str(s) for s in (v.get("surfaces") or ())),
            frozenset(str(f) for f in (v.get("files") or ())),
        )
        for v in raw_views
        if isinstance(v, Mapping) and v.get("name")
    }
    data_sigs: set[Tuple[str, str, str, str, str, str, str, str]] = set()
    for d in getattr(manifest, "data", ()) or ():
        if isinstance(d, Mapping):
            pol = d.get("policy") or {}
            purge = str(pol.get("purge", "")) if isinstance(pol, Mapping) else ""
            data_sigs.add((
                str(d.get("id", "")),
                str(d.get("kind", "")),
                str(d.get("path", "")),
                str(d.get("root_setting", "")),
                str(d.get("state_path", "")),
                str(d.get("default", "")),
                purge,
                str(d.get("provides", "")),
            ))
        else:
            pol = getattr(d, "policy", None)
            purge = str(getattr(pol, "purge", "") or "")
            data_sigs.add((
                str(getattr(d, "id", "")),
                str(getattr(d, "kind", "")),
                str(getattr(d, "path", "")),
                str(getattr(d, "root_setting", "")),
                str(getattr(d, "state_path", "")),
                str(getattr(d, "default", "")),
                purge,
                str(getattr(d, "provides", "")),
            ))

    return CapabilityBaseline(
        permissions=perms,
        network_hosts=net_hosts,
        lan_hosts=lan_hosts,
        secrets=frozenset(secrets_set),
        trust=str(getattr(manifest, "trust", "") or ""),
        services_consumes=frozenset(str(s) for s in (getattr(manifest, "services_consumes", ()) or ())),
        services_provides=services_provides,
        events_emit=frozenset(str(e) for e in (getattr(manifest, "events_emit", ()) or ())),
        events_allowed=events_allowed,
        subscriptions=subs,
        tools=tools,
        webhooks=webhooks,
        channels=channels,
        macros=macros,
        command_macros=command_macros,
        harnesses=harnesses,
        ai_features=ai_features,
        tier0=bool(getattr(manifest, "tier0", False)),
        run_mode=str(getattr(manifest, "run_mode", "rpc") or "rpc"),
        run_cmd=tuple(str(a) for a in (getattr(manifest, "run_cmd", ()) or ())),
        routes=frozenset(str(r) for r in (getattr(manifest, "routes", ()) or ())),
        timers=timers,
        views=views,
        topics=frozenset(str(t) for t in (getattr(manifest, "topics", ()) or ())),
        data=frozenset(data_sigs),
        owns_files=frozenset(str(f) for f in (getattr(getattr(manifest, "owns", None), "files", ()) or ())),
        ui_contribute_slots=frozenset(str(s) for s in ((getattr(manifest, "ui_contribute", None) or {}).keys() if isinstance(getattr(manifest, "ui_contribute", None), Mapping) else ())),
    )


def widening_reasons(base: CapabilityBaseline, cand: CapabilityBaseline) -> List[str]:
    reasons: List[str] = []
    if base.tier0 and not cand.tier0:
        reasons.append("run:tier0_escalation")
    elif not cand.tier0:
        if cand.run_mode != base.run_mode:
            reasons.append(f"run_mode:{cand.run_mode}")
        if cand.run_cmd != base.run_cmd:
            reasons.append(f"run_cmd:{' '.join(cand.run_cmd)}")
    for p in sorted(cand.permissions - base.permissions):
        reasons.append(f"permission:{p}")
    for host, (methods, paths, auth_sig) in sorted(cand.network_hosts.items()):
        if host not in base.network_hosts:
            reasons.append(f"network_host:{host}")
            continue
        b_methods, b_paths, b_auth = base.network_hosts[host]
        if not methods <= b_methods:
            reasons.append(f"network_methods:{host}:{','.join(sorted(methods - b_methods))}")
        if not _paths_covered(b_paths, paths):
            reasons.append(f"network_paths:{host}")
        if auth_sig and auth_sig != b_auth:
            reasons.append(f"network_auth:{host}")
    for entry, (methods, paths) in sorted(cand.lan_hosts.items()):
        if entry not in base.lan_hosts:
            reasons.append(f"lan_host:{entry}")
            continue
        b_methods, b_paths = base.lan_hosts[entry]
        if not methods <= b_methods:
            reasons.append(f"lan_methods:{entry}:{','.join(sorted(methods - b_methods))}")
        if not _paths_covered(b_paths, paths):
            reasons.append(f"lan_paths:{entry}")
    for sec in sorted(cand.secrets - base.secrets):
        reasons.append(f"secret:{sec}")
    if cand.trust == "unrestricted" and base.trust != "unrestricted":
        reasons.append("trust:unrestricted")
    for svc in sorted(cand.services_consumes - base.services_consumes):
        reasons.append(f"service_consume:{svc}")
    for sname, methods in sorted(cand.services_provides.items()):
        if sname not in base.services_provides:
            reasons.append(f"service_provide:{sname}")
        else:
            added = methods - base.services_provides[sname]
            if added:
                reasons.append(f"service_provide:{sname}:{','.join(sorted(added))}")
    for ev in sorted(cand.events_emit - base.events_emit):
        reasons.append(f"event_emit:{ev}")
    for ev in sorted(cand.events_allowed - base.events_allowed):
        reasons.append(f"event_allowed:{ev}")
    for sub in sorted(cand.subscriptions - base.subscriptions):
        reasons.append(f"subscription:{sub}")
    for name, gate in sorted(cand.tools - base.tools):
        reasons.append(f"tool:{name}:{gate}")
    for hook, sec, hdr in sorted(cand.webhooks - base.webhooks):
        reasons.append(f"webhook:{hook}:{sec}:{hdr}")
    for ch in sorted(cand.channels - base.channels):
        reasons.append(f"channel:{ch[0]}")
    for macro, _steps in sorted(cand.macros - base.macros):
        reasons.append(f"macro:{macro}")
    for cmd_id, _steps in sorted(cand.command_macros - base.command_macros):
        reasons.append(f"ui_command_macro:{cmd_id}")
    for h in sorted(cand.harnesses - base.harnesses):
        reasons.append(f"harness:{h}")
    for r in sorted(cand.routes - base.routes):
        reasons.append(f"route:{r}")
    for tname, every in sorted(cand.timers.items()):
        if tname not in base.timers or every < base.timers[tname]:
            reasons.append(f"timer:{tname}")
    for vname, (surfs, files) in sorted(cand.views.items()):
        if vname not in base.views or not (surfs <= base.views[vname][0]) or not (files <= base.views[vname][1]):
            reasons.append(f"view:{vname}")
    for t in sorted(cand.topics - base.topics):
        reasons.append(f"topic:{t}")
    for d in sorted(cand.data - base.data):
        reasons.append(f"data:{d[0]}")
    for f in sorted(cand.owns_files - base.owns_files):
        reasons.append(f"owns_file:{f}")
    for s in sorted(cand.ui_contribute_slots - base.ui_contribute_slots):
        reasons.append(f"ui_slot:{s}")
    for feat, (cap, calls, toks) in sorted(cand.ai_features.items()):
        if feat not in base.ai_features:
            reasons.append(f"ai_feature:{feat}:{cap}")
        else:
            b_cap, b_calls, b_toks = base.ai_features[feat]
            if cap != b_cap or calls > b_calls or toks > b_toks:
                reasons.append(f"ai_feature:{feat}:{cap}")
    return reasons


@dataclass(frozen=True)
class DevLease:

    plugin_id: str
    install_key: str
    source_realpath: str
    baseline: CapabilityBaseline
    baseline_sha: str
    created_at: float
    expires_at: float
    lease_token: str


class DevTrustLeaseStore:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._leases: Dict[str, DevLease] = {}

    def acquire(
        self,
        plugin_id: str,
        install_key: str,
        source_path: Path | str,
        manifest: Any,
        *,
        ttl: float = DEFAULT_TTL_SECONDS,
    ) -> DevLease:
        now = self._clock()
        ttl_clamped = max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, float(ttl)))
        baseline = extract_baseline(manifest)
        lease = DevLease(
            plugin_id=plugin_id,
            install_key=install_key,
            source_realpath=os.path.realpath(source_path),
            baseline=baseline,
            baseline_sha=baseline.canonical_sha(),
            created_at=now,
            expires_at=now + ttl_clamped,
            lease_token=secrets.token_urlsafe(18),
        )
        with self._lock:
            self._leases[plugin_id] = lease
        return lease

    def get(self, plugin_id: str) -> Optional[DevLease]:
        with self._lock:
            lease = self._leases.get(plugin_id)
            if lease is None:
                return None
            if self._clock() >= lease.expires_at:
                self._leases.pop(plugin_id, None)
                return None
            return lease

    def renew(
        self,
        plugin_id: str,
        *,
        ttl: float = DEFAULT_TTL_SECONDS,
        lease_token: Optional[str] = None,
    ) -> Optional[DevLease]:
        with self._lock:
            lease = self.get(plugin_id)
            if lease is None:
                return None
            if lease_token is not None and lease.lease_token != lease_token:
                return None
            ttl_clamped = max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, float(ttl)))
            updated = DevLease(
                plugin_id=lease.plugin_id,
                install_key=lease.install_key,
                source_realpath=lease.source_realpath,
                baseline=lease.baseline,
                baseline_sha=lease.baseline_sha,
                created_at=lease.created_at,
                expires_at=self._clock() + ttl_clamped,
                lease_token=lease.lease_token,
            )
            self._leases[plugin_id] = updated
            return updated

    def revoke_plugin(self, plugin_id: str) -> bool:
        with self._lock:
            return self._leases.pop(plugin_id, None) is not None

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._leases)
            self._leases.clear()
            return count

    def check_reload(
        self,
        plugin_id: str,
        install_key: str,
        source_path: Path | str,
        new_manifest: Any,
    ) -> Tuple[bool, str, List[str]]:
        with self._lock:
            lease = self._leases.get(plugin_id)
            if lease is None:
                return False, "no_lease", []
            if self._clock() >= lease.expires_at:
                self._leases.pop(plugin_id, None)
                return False, "lease_expired", []
            if lease.install_key != install_key:
                self._leases.pop(plugin_id, None)
                return False, "install_changed", []
            if lease.source_realpath != os.path.realpath(source_path):
                self._leases.pop(plugin_id, None)
                return False, "source_mismatch", []
            widened = widening_reasons(lease.baseline, extract_baseline(new_manifest))
            if widened:
                self._leases.pop(plugin_id, None)
                return False, "permission_widened", widened
            return True, "", []


_STORES_LOCK = threading.RLock()
_STORES: Dict[str, DevTrustLeaseStore] = {}


def store_for(state_dir: Path) -> DevTrustLeaseStore:
    key = os.path.realpath(state_dir)
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            store = DevTrustLeaseStore()
            _STORES[key] = store
        return store
