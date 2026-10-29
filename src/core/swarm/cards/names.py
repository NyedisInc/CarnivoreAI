
from __future__ import annotations

from typing import FrozenSet

CARD_TOOLS: FrozenSet[str] = frozenset({
    "swarm_card_list", "swarm_card_get", "swarm_card_board", "swarm_card_create", "swarm_card_start", "swarm_card_handoff",
    "swarm_card_finish", "swarm_card_release", "swarm_card_reorder", "swarm_card_deal",
    "swarm_card_grant", "swarm_card_pace", "swarm_card_capacity", "swarm_card_verdict",
    "swarm_card_auto_promote", "swarm_card_queue",
})

OWNER_ONLY_CARD_TOOLS: FrozenSet[str] = frozenset({"swarm_card_grant", "swarm_card_pace"})
