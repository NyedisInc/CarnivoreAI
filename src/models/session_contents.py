
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ContentsItem(BaseModel):
    """One listed thing: a skill, instruction file, agent, command, hook, settings layer, MCP server or plugin."""

    name: str
    scope: str = Field(description="global, project or plugin")
    path: Optional[str] = Field(None, description="the file or folder it came from")
    description: str = Field("", description="the front matter description, else the first meaningful line")
    detail: str = Field("", description="a short fact: line count, MCP transport and command name, hook program, plugin state")
    lines: Optional[int] = Field(None, description="lines in the item's file; null for a folder, a shared file or an unreadable one")
    open_root: Optional[str] = Field(None, description="workdir or user: the root the Files tab opens the file by; null when it cannot open")
    open_path: Optional[str] = Field(None, description="the file's path relative to open_root; null with open_root")
    status: str = Field("available", description="loaded (read at session start), available (can be loaded) or disabled (its plugin is off)")


class ContentsSection(BaseModel):
    """All items of one kind."""

    kind: str = Field(description="instructions, skills, agents, commands, hooks, output_styles, settings, mcp, plugins, prompts or profiles")
    items: List[ContentsItem]
    truncated: bool = Field(False, description="more items exist than the cap returned")


class SessionContents(BaseModel):
    """What a session has loaded or available."""

    session_uuid: str
    row_id: int
    family: str = Field(description="claude or codex")
    config_dir: str = Field(description="the pane's CLAUDE_CONFIG_DIR or CODEX_HOME, else the default")
    working_dir: Optional[str] = None
    sections: List[ContentsSection]
