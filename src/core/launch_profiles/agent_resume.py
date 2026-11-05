
from __future__ import annotations

import re
import shlex
from typing import Iterable, Optional

from src.config.launch_profiles import RESUME_ID_PLACEHOLDER, AgentDefinition

_RESUME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")


class ResumePrefixNotApproved(PermissionError):

    def __init__(self, prefix: str, tmux_name: str = "", ask: bool = False) -> None:
        super().__init__(f"resume command prefix {prefix!r} is not approved on this computer")
        self.prefix, self.tmux_name, self.ask = prefix, tmux_name, ask


def valid_resume_id(value: Optional[str]) -> Optional[str]:
    return value if value and _RESUME_ID.match(value) else None


def resume_command(agent: Optional[AgentDefinition], resume_id: Optional[str],
                   approved: Iterable[str]) -> Optional[str]:
    if agent is None or not agent.resume:
        return None
    rid = valid_resume_id(resume_id)
    if rid is None:
        return None
    words = shlex.split(agent.resume)
    if words[0] not in set(approved):
        raise ResumePrefixNotApproved(words[0])
    return " ".join(shlex.quote(w.replace(RESUME_ID_PLACEHOLDER, rid)) for w in words)
