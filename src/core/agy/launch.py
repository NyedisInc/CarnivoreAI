
from __future__ import annotations

import shlex
from typing import Any, Dict, Optional

from src.core.agy.identity import is_agy_profile

LINE_ENV = "CARNIVORE_AGY_LAUNCH_LINE"
OSC_ENV = "AGY_CLI_OSC7501"


def launch_env(launch_line: Optional[str]) -> Dict[str, str]:
    env = {OSC_ENV: "on"}
    if launch_line:
        env[LINE_ENV] = launch_line
    return env


def wrap_command(profile: Any, command: str, launch_line: Optional[str]) -> str:
    if not is_agy_profile(profile):
        return command
    assigns = " ".join("%s=%s" % (k, shlex.quote(v)) for k, v in launch_env(launch_line).items())
    return "export %s; %s" % (assigns, command)
