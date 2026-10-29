
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.core.conversation_writers import ProcessTable
from src.core.mcp_health.client_log import LinkState
from src.core.mcp_health.monitor import Measure, Target
from src.core.mcp_health.servers import STDIO_GRACE

MAX_TEXT = 80
MAX_PROCESSES = 2000
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.+][A-Za-z0-9_.+-]*")


def basename(command: Optional[str]) -> Optional[str]:
    tokens = (command or "").split()
    name = os.path.basename(tokens[0].rstrip("/"))[:MAX_TEXT] if tokens else ""
    return name if _SAFE_NAME.fullmatch(name) else None


def process_rows(table: ProcessTable, targets: Iterable[Target], roots: Mapping[str, int]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for target in targets:
        root = roots.get(target.session_id)
        if root is None or root not in table.rows:
            continue
        for proc in table.descendants(root):
            if len(out) >= MAX_PROCESSES:
                return out
            out.append({"pid": proc.pid, "ppid": proc.ppid, "name": basename(proc.command) or "", "session": target.session_id})
    return out


def _alive(measure: Measure, key: str, now: datetime) -> Optional[bool]:
    seen = measure.alive.get(key)
    if seen is False and (measure.agent_started_at is None or now - measure.agent_started_at <= STDIO_GRACE):
        return None
    return seen


def config_rows(targets: Iterable[Target], measures: Mapping[str, Measure], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for target in targets:
        measure = measures.get(target.session_id)
        if measure is None:
            continue
        servers = [{"name": s.name[:MAX_TEXT], "transport": s.transport, "scope": s.scope[:MAX_TEXT], "command": basename(s.command),
                    "alive": _alive(measure, s.key, now)} for s in measure.specs]
        out.append({"session": target.session_id, "family": target.family, "servers": servers, "excluded": sorted(measure.excluded)})
    return out


def link_rows(targets: Iterable[Target], measures: Mapping[str, Measure]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for target in targets:
        measure = measures.get(target.session_id)
        if measure is None:
            continue
        links: Dict[str, LinkState] = measure.links or {}
        out.append({"session": target.session_id, "links": [
            {"name": link.dir_name[:MAX_TEXT], "transport": link.transport, "state": link.state, "reason": link.reason}
            for _, link in sorted(links.items())]})
    return out
