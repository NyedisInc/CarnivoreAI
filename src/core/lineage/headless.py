"""Transcript heads and the headless-worker inference: which session launched a ``claude -p`` conversation.

Every top-level transcript's head names its ``entrypoint`` (``cli`` and ``claude-desktop`` are typed into by a
person; ``sdk-cli`` and the SDKs are headless workers), its folder and its first timestamp. Nothing on disk says
which session ran a headless worker, so the link is INFERRED (``inferred_active_session``): the worker began
while exactly ONE human conversation in the same project folder was active (begun, and its file not yet last
written). When that human conversation belongs to a Carnivore session the edge is session -> worker, otherwise
human conversation -> worker. Two or more active candidates is ambiguous and writes nothing. Reads only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.lineage import constants as K


@dataclass(frozen=True)
class Head:

    conversation_id: str
    folder: str
    entrypoint: Optional[str]
    started: Optional[float]
    last_write: float

    @property
    def level(self) -> Optional[str]:
        return K.LEVEL_BY_ENTRYPOINT.get(self.entrypoint or "")


def epoch_of(stamp: object) -> Optional[float]:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def read_head(path: Path) -> Head:
    with path.open("rb") as handle:
        raw = handle.read(K.HEAD_BYTES)
    last_write = path.stat().st_mtime
    entrypoint: Optional[str] = None
    started: Optional[float] = None
    for line in raw.split(b"\n")[: K.HEAD_RECORDS]:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        entrypoint = entrypoint or (record.get("entrypoint") if isinstance(record.get("entrypoint"), str) else None)
        started = started if started is not None else epoch_of(record.get("timestamp"))
        if entrypoint and started is not None:
            break
    return Head(path.stem, str(path.parent), entrypoint, started, last_write)


@dataclass
class Inference:

    edges: List[Tuple[str, str, str]]
    ambiguous: int = 0
    no_candidate: int = 0


def infer_spawns(heads: Sequence[Head], session_of: Dict[str, str]) -> Inference:
    by_folder: Dict[str, List[Head]] = {}
    for head in heads:
        by_folder.setdefault(head.folder, []).append(head)
    found = Inference(edges=[])
    for group in by_folder.values():
        humans = [h for h in group if h.level == K.LEVEL_HUMAN and h.started is not None]
        for worker in group:
            if worker.level != K.LEVEL_SUBSESSION or worker.started is None:
                continue
            active = [h for h in humans if h.conversation_id != worker.conversation_id
                      and h.started <= worker.started <= h.last_write]
            owners = {session_of.get(h.conversation_id) for h in active}
            if not active:
                found.no_candidate += 1
            elif len(owners) == 1 and None not in owners:
                found.edges.append((K.NODE_SESSION, owners.pop(), worker.conversation_id))
            elif len(active) == 1:
                found.edges.append((K.NODE_CONVERSATION, active[0].conversation_id, worker.conversation_id))
            else:
                found.ambiguous += 1
    return found
