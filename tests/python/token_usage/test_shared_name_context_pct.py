from __future__ import annotations

import sqlite3
from typing import Any, Dict

from src.core.listing_attention import conversation_for_instance
from src.core.session_instance_index import build_instance_index
from src.core.session_token_usage.listing_model_facts import build_model_listing_prefetch

STOPPED_EPOCH = 1792412477
RUNNING_EPOCH = 1793123878
OTHER_EPOCH = 1793044132


class _Usage:

    def __init__(self, remaining: float) -> None:
        self.state = "ok"
        self.model = "claude-opus-5-5"
        self.effort = "medium"
        self.model_cost_tier = 4
        self.context_remaining_pct = remaining
        self.context_window_tokens = 1000
        self.context_used_tokens = round((100.0 - remaining) * 10)


class _Prefetch:

    def has(self, name: str) -> bool:
        return True

    def identity_for(self, name: str) -> Dict[str, Any]:
        return {"agent_family": "claude"}


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, parent_session_id INTEGER, agent_type TEXT, "
        "agent_family TEXT, agent_family_source TEXT, title TEXT, tmux_socket TEXT, tmux_name TEXT, "
        "tmux_created_epoch INTEGER, activity_state TEXT, activity_state_at TEXT, "
        "claude_session_uuid TEXT, working_dir TEXT, lifecycle TEXT)"
    )
    rows = [
        (43, "carnivore_Agent_-_Cloude_Code", OTHER_EPOCH, "uuid-43", "Carnivore", "running"),
        (970, "carnivore_Carnivore", STOPPED_EPOCH, "uuid-970", "Carnivore - Crates", "stopped"),
        (1006, "carnivore_Carnivore", RUNNING_EPOCH, "uuid-1006", "Carnivore", "running"),
    ]
    for row_id, name, epoch, uuid, title, lifecycle in rows:
        conn.execute(
            "INSERT INTO sessions (id, agent_type, agent_family, agent_family_source, title, tmux_socket, "
            "tmux_name, tmux_created_epoch, claude_session_uuid, working_dir, lifecycle) "
            "VALUES (?, 'claude-skip-permissions', 'claude', 'launched', ?, 'cloude', ?, ?, ?, '/w', ?)",
            (row_id, title, name, epoch, uuid, lifecycle),
        )
    return conn


def test_running_row_reads_its_own_conversation_not_the_stopped_twin() -> None:
    index = build_instance_index(_db(), socket="cloude", names=["carnivore_Carnivore", "carnivore_Agent_-_Cloude_Code"])
    status_map = {
        "carnivore_Carnivore": {"created_at_epoch": RUNNING_EPOCH},
        "carnivore_Agent_-_Cloude_Code": {"created_at_epoch": OTHER_EPOCH},
    }
    remaining = {"uuid-1006": 70.0, "uuid-43": 80.0}
    read: list = []

    def read_usage(subject: Any, **_kw: Any) -> _Usage:
        read.append(subject.conversation_uuid)
        return _Usage(remaining[subject.conversation_uuid])

    facts = build_model_listing_prefetch(
        names=["carnivore_Carnivore", "carnivore_Agent_-_Cloude_Code"],
        status_map=status_map,
        instance_index=index,
        prefetch=_Prefetch(),
        conversation_for_instance=conversation_for_instance,
        read_usage=read_usage,
    )
    assert facts["carnivore_Carnivore"].context_used_pct == 30.0
    assert facts["carnivore_Agent_-_Cloude_Code"].context_used_pct == 20.0
    assert "uuid-970" not in read
