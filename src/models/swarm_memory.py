
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SwarmMemoryFileRow(BaseModel):
    """One editable file: MEMORY.md or a fact (``state`` live or held; null for MEMORY.md)."""

    path: str
    title: str
    state: Optional[Literal["live", "held"]] = None


class SwarmMemoryBackup(BaseModel):
    """One kept version of a file, ``at`` ISO UTC."""

    id: str
    at: str


class SwarmMemoryFile(BaseModel):
    """One file's text and its backups, newest first."""

    path: str
    text: str
    backups: List[SwarmMemoryBackup]


class SwarmMemorySave(BaseModel):
    """``PUT /swarm/agents/{id}/memory/file``: the file and its new text."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=64)
    text: str = Field(max_length=64_000)


class SwarmMemoryRestore(BaseModel):
    """``POST /swarm/agents/{id}/memory/restore``: the file and a backup id (omitted: the newest, which is undo)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=64)
    backup_id: Optional[str] = Field(default=None, max_length=32)
