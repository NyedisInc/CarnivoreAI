
from __future__ import annotations

import os

from src.core.product_identity import env_value

CONTROL_INPUT_SESSION_PREFIX = "_carnivore_ctl_in_"

CONTROL_INPUT_ENV_SUFFIX = "CONTROL_INPUT"

CONTROL_INPUT_DEFAULT_ON = True


def control_input_session_name(pid: int | None = None) -> str:
    return f"{CONTROL_INPUT_SESSION_PREFIX}{os.getpid() if pid is None else pid}"


def is_control_input_session(name: str) -> bool:
    return name.startswith(CONTROL_INPUT_SESSION_PREFIX)


def control_input_enabled() -> bool:
    raw = (env_value(CONTROL_INPUT_ENV_SUFFIX) or "").strip()
    if raw == "0":
        return False
    if raw == "1":
        return True
    return CONTROL_INPUT_DEFAULT_ON
