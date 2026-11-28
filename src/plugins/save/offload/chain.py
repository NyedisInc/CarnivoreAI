
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Mapping, Set, Tuple

from src.plugins.sdk.session_chains import ChainSnapshot, SessionFacts


@dataclass(frozen=True)
class ChainMap:

    sessions: Mapping[str, SessionFacts]
    chains: Mapping[str, Tuple[str, ...]]
    owners: Mapping[str, FrozenSet[str]]

    def owners_of(self, conversation_id: str) -> FrozenSet[str]:
        return self.owners.get(conversation_id, frozenset())


def _walk_up(seeds: List[str], parents: Mapping[str, FrozenSet[str]]) -> List[str]:
    seen: Dict[str, None] = {}
    queue = list(seeds)
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen[node] = None
        queue.extend(sorted(parents.get(node, ())))
    return list(seen)


def build(snapshot: ChainSnapshot) -> ChainMap:
    chains: Dict[str, Tuple[str, ...]] = {}
    owners: Dict[str, Set[str]] = {}
    for facts in snapshot.sessions:
        seeds = ([facts.claude_session_uuid] if facts.claude_session_uuid else []) + sorted(snapshot.session_parents.get(facts.session_uuid, ()))
        chain = tuple(_walk_up(seeds, snapshot.conversation_parents))
        chains[facts.session_uuid] = chain
        for conversation in chain:
            owners.setdefault(conversation, set()).add(facts.session_uuid)
    return ChainMap({s.session_uuid: s for s in snapshot.sessions}, chains, {c: frozenset(o) for c, o in owners.items()})
