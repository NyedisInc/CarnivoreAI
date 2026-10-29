
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from mh_vocab import (
    ALERT_STATES, DROP_DROPPED, DROP_NEEDS_AUTH, REASON_CONNECTED, REASON_NOT_FOUND, REASON_NOT_IMPLEMENTED, REASON_NOT_SEEN, REASON_PROCESS_GONE, REASON_PROCESS_RUNNING, SOURCE_CLIENT_LOG,
    SOURCE_PROBE, SOURCE_PROCESS, STATE_CONNECTED, STATE_DOWN, STATE_NEEDS_AUTH, STATE_UNKNOWN, TRANSPORT_STDIO, TRANSPORT_UNKNOWN, Health, Link,
    ServerSpec)


@dataclass(frozen=True)
class Evidence:

    specs: Tuple[ServerSpec, ...]
    excluded: FrozenSet[str] = frozenset()
    links: Optional[Mapping[str, Link]] = None
    alive: Mapping[str, Optional[bool]] = field(default_factory=dict)


def judge(spec: ServerSpec, ev: Evidence) -> Health:
    link = (ev.links or {}).get(spec.key)
    transport = spec.transport if spec.transport != TRANSPORT_UNKNOWN or link is None else link.transport
    gone = spec.transport == TRANSPORT_STDIO and ev.alive.get(spec.key) is False
    if link is not None and link.state != STATE_CONNECTED and not (gone and link.state == STATE_UNKNOWN):
        return Health(spec.name, transport, link.state, link.reason, SOURCE_CLIENT_LOG)
    if gone:
        return Health(spec.name, transport, STATE_DOWN, REASON_PROCESS_GONE, SOURCE_PROCESS)
    if link is not None:
        return Health(spec.name, transport, link.state, link.reason, SOURCE_CLIENT_LOG)
    if spec.transport == TRANSPORT_STDIO and ev.alive.get(spec.key) is True:
        return Health(spec.name, transport, STATE_CONNECTED, REASON_PROCESS_RUNNING, SOURCE_PROCESS)
    return Health(spec.name, transport, STATE_UNKNOWN, REASON_NOT_SEEN, SOURCE_PROCESS if spec.transport == TRANSPORT_STDIO else SOURCE_PROBE)


def _is_not_implemented(health: Health) -> bool:
    return health.state == STATE_DOWN and health.reason == REASON_NOT_IMPLEMENTED


def judge_session(ev: Evidence) -> Tuple[Health, ...]:
    out: Dict[str, Health] = {}
    for spec in ev.specs:
        if spec.key and spec.key not in ev.excluded and spec.key not in out:
            out[spec.key] = judge(spec, ev)
    for key, link in (ev.links or {}).items():
        if key in out or key in ev.excluded:
            continue
        health = judge(ServerSpec(name=link.name, transport=link.transport, scope="client_log"), ev)
        if _is_not_implemented(health):
            health = Health(health.name, health.transport, STATE_UNKNOWN, REASON_NOT_FOUND, health.source)
        out[key] = Health(health.name, health.transport, health.state, health.reason, health.source, exact=False)
    return tuple(sorted(out.values(), key=lambda h: h.name.lower()))


def as_drops(servers: Iterable[Health]) -> List[Dict[str, object]]:
    return [{"name": s.name, "state": DROP_NEEDS_AUTH if s.state == STATE_NEEDS_AUTH else DROP_DROPPED, "exact": s.exact, "source": s.source}
            for s in servers if s.state in ALERT_STATES]
