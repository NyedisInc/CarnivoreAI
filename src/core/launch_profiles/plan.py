
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

Purpose = Literal["pane", "headless", "preview"]
PURPOSES = ("pane", "headless", "preview")


@dataclass(frozen=True)
class LaunchDisplay:

    label: str
    harness: str
    account: str
    model: str
    permissions: str
    endpoint: str = ""
    key_hint: str = ""


@dataclass(frozen=True)
class ScriptFile:

    path: str
    content: str


@dataclass(frozen=True)
class LaunchPlan:

    command: str
    argv_tail: Tuple[str, ...]
    env_set: Tuple[Tuple[str, str], ...]
    env_unset: Tuple[str, ...]
    secret_refs: Tuple[Tuple[str, str], ...]
    display: LaunchDisplay
    digest: str
    purpose: Purpose
    script_file: Optional[ScriptFile] = None
    profile_id: str = ""
    account_mode: str = "follow_active"
    connection_id: str = ""
