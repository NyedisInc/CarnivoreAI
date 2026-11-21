
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "flow_get": ("conversations.flow.get",
                 "Rebuild a multi-agent run as a swimlane flow chart (sessions, subagents, crosstalk, spawns, task manager posts), "
                 "seeded by a task manager item or a session; html true gives one self-contained page."),
}
