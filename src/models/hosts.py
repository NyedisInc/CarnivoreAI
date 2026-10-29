
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class HostModel(BaseModel):
    """One host. The probe fields are null until something probes it (slice S2)."""

    key: str = Field(..., description="Stable id; 'local' is this machine")
    label: str
    local: bool = Field(..., description="True only for this machine")
    ssh_target: Optional[str] = Field(None, description="ssh alias or user@host; null for this machine")
    ssh_port: Optional[int] = Field(None, description="null: the ssh config decides")
    socket: Optional[str] = Field(
        None, description="tmux socket on that machine; null for this machine (config.json decides)"
    )
    enabled: bool
    session_count: int = Field(..., description="Unarchived sessions rows on this host")
    probe_state: str = Field(..., description="'never' until the first probe")
    probe_detail: Optional[str] = None
    probed_at: Optional[str] = None
    tmux_path: Optional[str] = None
    tmux_version: Optional[str] = None
    login_path: Optional[str] = None
    agent_paths: Optional[Dict[str, str]] = None
    login_shell: Optional[str] = None
    machine_id: Optional[str] = None
    remote_carnivore: Optional[str] = None
    computer_install_id: Optional[str] = Field(None, description="Install id of the Pack computer the owner linked this ssh host to; null until linked")
    created_at: str
    updated_at: str


class HostsResponse(BaseModel):
    """Every host, plus whether that is known.

    ``status='unavailable'`` with ``hosts=[]`` means the table could not be
    read, which is not the same claim as an install with no hosts.
    """

    status: str = Field(..., description="'ok' or 'unavailable'")
    detail: Optional[str] = None
    hosts: List[HostModel] = Field(default_factory=list)


class CreateHostRequest(BaseModel):
    """Add a machine by its ssh target. Stores it; nothing is contacted yet.

    ``key`` is not a field here (the owner, 2026-09-28): the server
    generates it, so a body carrying one is rejected as an unknown field
    (``extra="forbid"``) rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    ssh_target: str = Field(..., description="An ~/.ssh/config alias or user@host")
    ssh_port: Optional[StrictInt] = None
    socket: Optional[str] = Field(None, description="Default 'carnivore-remote'")


class UpdateHostRequest(BaseModel):
    """Change a remote host; an absent or null field is left alone."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = None
    enabled: Optional[StrictBool] = None
    socket: Optional[str] = None


class LinkComputerRequest(BaseModel):
    """Say which Pack computer an ssh host belongs to; null clears the link."""

    model_config = ConfigDict(extra="forbid")

    computer_install_id: Optional[str] = Field(..., description="A Pack computer's install id, or null to clear")


class HostDeletedResponse(BaseModel):
    """A host that was deleted. Nothing on that machine was touched."""

    key: str
    deleted: bool = True
