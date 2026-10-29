
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import ValidationError

from src.core.federation.peer_fanout import PeerAnswer, unavailable_marker
from src.models.project_history import HistoryGroup

@dataclass(frozen=True)
class Held:

    conversations: Set[str]
    shadows: Set[Tuple[str, Optional[str]]]


def _peer_group(raw: Any, a: PeerAnswer, held: "Held") -> Optional[HistoryGroup]:
    group = HistoryGroup.model_validate(raw)
    kept, dropped = [], 0
    for s in group.sessions:
        if (s.claude_session_uuid and s.claude_session_uuid in held.conversations) or (a.host_key, s.tmux_name) in held.shadows:
            dropped += 1
            group.counts[s.state] = max(0, group.counts.get(s.state, 0) - 1)
            continue
        kept.append(s.model_copy(update={"host_key": a.host_key, "host_label": a.label, "live_session_id": None}))
    if dropped and not kept and group.session_total <= dropped:
        return None
    return group.model_copy(update={"key": f"{a.host_key}:{group.key}", "sessions": kept,
                                    "session_total": max(0, group.session_total - dropped),
                                    "host_key": a.host_key, "host_label": a.label})


def merge_history(local: Dict[str, Any], answers: Iterable[PeerAnswer], held: "Held") -> Dict[str, Any]:
    groups: List[HistoryGroup] = []
    failed: List[PeerAnswer] = []
    for a in answers:
        if a.data is None:
            failed.append(a)
            continue
        raw_groups = a.data.get("groups") if isinstance(a.data, dict) else None
        try:
            if not isinstance(raw_groups, list):
                raise TypeError("groups")
            groups.extend([g for g in (_peer_group(r, a, held) for r in raw_groups) if g is not None])
        except (ValidationError, TypeError):
            failed.append(PeerAnswer(a.host_key, a.label, None, "bad_answer"))
    return {**local, "peer_groups": groups, "peer_unavailable": unavailable_marker(failed)}
