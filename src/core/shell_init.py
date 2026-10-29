
from __future__ import annotations

import shlex

RC_SOURCE = "source ~/.zshrc >/dev/null 2>&1 </dev/null"


def rc_prefixed(command: str) -> str:
    return f"zsh -c {shlex.quote(f'{RC_SOURCE}; {command}')}"
