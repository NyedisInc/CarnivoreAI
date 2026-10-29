from __future__ import annotations

import re
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_TOOLS: Tuple[str, ...] = ("Read", "Grep", "Glob", "WebSearch", "WebFetch")
WRITE_TOOLS = ("Edit", "Write", "NotebookEdit", "Bash")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")

_TOOL_ENTRY = re.compile(r"[A-Za-z_][A-Za-z0-9_.*-]{0,127}(\([A-Za-z0-9_./:*=@+-]([A-Za-z0-9_./:*=@+ -]{0,254}[A-Za-z0-9_./:*=@+-])?\))?")

LEVELS = {"read_only": ("dontAsk", False), "edits_in_folder": ("acceptEdits", True), "unattended": ("bypassPermissions", False)}


class AgentDef(BaseModel):
    """One cron agent. ``extra="forbid"``: an unknown key is a typo, never silently dropped."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["agent"] = "agent"
    name: str = Field(default="", max_length=120)
    folder: str = Field(min_length=1, max_length=4096)
    prompt: str = Field(min_length=1, max_length=32 << 10)
    system_prompt_append: Optional[str] = Field(default=None, max_length=8 << 10)
    model: Optional[str] = None
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = None
    tools: List[str] = Field(default_factory=lambda: list(DEFAULT_TOOLS))
    permission: Literal["read_only", "edits_in_folder", "unattended"] = "read_only"
    max_turns: int = Field(default=30, ge=1, le=200)
    max_budget_usd: float = Field(default=1.0, ge=0.05, le=50)
    timeout_s: float = Field(default=1800.0, ge=60, le=3600)
    login_account_id: Optional[str] = None
    api_key_connection_id: Optional[str] = None
    settings: Literal["isolated", "normal"] = "isolated"
    acknowledge_unattended: Optional[str] = None

    @model_validator(mode="after")
    def _checks(self) -> "AgentDef":
        if "\x00" in self.prompt or "\x00" in (self.system_prompt_append or ""):
            raise ValueError("text may not contain NUL")
        if self.prompt.startswith("-"):
            raise ValueError("the prompt may not start with '-'")
        if any(not _TOOL_ENTRY.fullmatch(t) for t in self.tools):
            raise ValueError("a tool entry is a name or Name(pattern) whose pattern has no comma or parenthesis and no leading or trailing space")
        names = [t.split("(")[0] for t in self.tools]
        bare = {t for t in self.tools if "(" not in t}
        if self.permission == "read_only" and any(n in WRITE_TOOLS for n in names):
            raise ValueError("tools_not_allowed_for_level: read_only carries no Edit, Write, NotebookEdit or Bash")
        if self.permission == "edits_in_folder" and "Bash" in bare:
            raise ValueError("tools_not_allowed_for_level: Bash needs a command pattern at edits_in_folder")
        return self

    def mode(self) -> Tuple[str, bool]:
        return LEVELS[self.permission]

    def isolated(self) -> bool:
        return self.settings == "isolated" or self.permission == "edits_in_folder"
