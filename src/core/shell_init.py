
from __future__ import annotations

import os
import shlex

RC_SOURCE = "source ~/.zshrc >/dev/null 2>&1 </dev/null"


def _install_dirs_on_path() -> str:
    from src.core.kill_guard.shims import pane_guard_dir
    from src.core.launch_profiles.installed import path_with_install_dirs

    guard = pane_guard_dir()
    folders = [d for d in path_with_install_dirs("").split(os.pathsep) if d]
    if not folders and not guard:
        return ""
    text = "typeset -U path; "
    if guard:
        text += f"path=({shlex.quote(guard)} $path); "
    if folders:
        text += f"path+=({' '.join(shlex.quote(d) for d in folders)}); "
    return text


def rc_prefixed(command: str) -> str:
    return f"zsh -c {shlex.quote(f'{RC_SOURCE}; {_install_dirs_on_path()}{command}')}"
