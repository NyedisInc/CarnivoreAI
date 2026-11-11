
from __future__ import annotations

import os
import shlex

RC_SOURCE = "source ~/.zshrc >/dev/null 2>&1 </dev/null"


def _install_dirs_on_path() -> str:
    from src.core.launch_profiles.installed import path_with_install_dirs

    folders = [d for d in path_with_install_dirs("").split(os.pathsep) if d]
    if not folders:
        return ""
    return f"typeset -U path; path+=({' '.join(shlex.quote(d) for d in folders)}); "


def rc_prefixed(command: str) -> str:
    return f"zsh -c {shlex.quote(f'{RC_SOURCE}; {_install_dirs_on_path()}{command}')}"
