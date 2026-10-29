
from typing import List

from pydantic import BaseModel, Field

from src.core.agent_wrappers import AgentWrapper


class AgentsConfig(BaseModel):
    """The ``agents`` block of config.json: the launch wrappers.

    Every session launches through a wrapper (``src/core/agent_wrappers.py``,
    resolved in ``src/config/agent_command.py``). The per-family
    ``claude_command`` / ``codex_command`` / ``hermes_command`` /
    ``openclaw_command`` / ``local_command`` / ``shell_command`` strings
    were retired on 2026-09-28 (Joe (ccsliinc): "the wrappers page is the
    single home"); config migration v6 folded any customised one into its
    family's wrappers (``src/core/launch_wrappers/legacy_fold.py``). They
    are no longer fields here: an old config.json that still carries them
    loads fine (pydantic ignores the extra keys) and nothing reads them.
    """
    wrappers: List[AgentWrapper] = Field(default_factory=list)
