
from __future__ import annotations

import fnmatch
import os
import re
import shlex
from typing import List, Optional, Sequence, Tuple

from src.core.pack.placement.needs import Need

SELF_LOCAL_LABELS = frozenset({"this-mac", "this-computer", "local", "self"})

_LOCAL_DAEMON_PROGRAMS = frozenset({
    "launchctl", "osascript", "open", "pbcopy", "pbpaste", "defaults", "security", "brew", "pmset", "ioreg",
    "scutil", "networksetup", "diskutil", "mdfind", "mdutil", "caffeinate", "killall", "pkill",
})

BUILTIN_LOCAL_SCRIPTS = (
    "scripts/dist-at-merge.sh",
    "scripts/refresh-local-install.sh",
    "scripts/test-remote.sh",
)

_PORTABLE_PREFIXES = (
    "/dev/", "/usr/bin", "/usr/local/bin", "/opt/homebrew", "/bin/", "/sbin/", "/usr/sbin", "/etc/",
)

_ABS_PATH_RE = re.compile(r"(?:^|[=:\s'\"(])((?:/Users/|/home/|/Applications/|/Library/|~/|\$HOME/|\$\{HOME\}/)[^\s'\"`;|&)>]+)")


def is_self_local_need(need: Need) -> bool:
    return need.kind == "label" and need.name in SELF_LOCAL_LABELS


def split_self_local_needs(needs: Sequence[Need]) -> Tuple[bool, List[Need]]:
    pinned = any(is_self_local_need(n) for n in needs)
    remaining = [n for n in needs if not is_self_local_need(n)]
    return pinned, remaining


def _inside(path: str, root: str) -> bool:
    norm_root = os.path.normpath(root).rstrip("/")
    norm_path = os.path.normpath(path)
    return norm_path == norm_root or norm_path.startswith(norm_root + "/")


def _expand_path(raw: str) -> str:
    if raw.startswith("~/"):
        return os.path.expanduser(raw)
    home = os.path.expanduser("~")
    if raw.startswith("$HOME/"):
        return home + raw[len("$HOME"):]
    if raw.startswith("${HOME}/"):
        return home + raw[len("${HOME}"):]
    return raw


def _outside_project_path(command: str, project_root: str) -> Optional[str]:
    if not project_root:
        return None
    real_root = os.path.realpath(project_root)
    roots = (os.path.normpath(project_root), real_root)
    for match in _ABS_PATH_RE.finditer(command):
        raw = match.group(1)
        if any(raw.startswith(p) for p in _PORTABLE_PREFIXES):
            continue
        cleaned = raw.rstrip(".,:")
        expanded = _expand_path(cleaned)
        if any(_inside(expanded, r) or _inside(os.path.realpath(expanded), r) for r in roots):
            continue
        return cleaned
    return None


def _tokens(command: str) -> List[str]:
    try:
        lexer = shlex.shlex(command.split("<<", 1)[0], posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def local_only_reason(command: str, folder: str, project_root: str, *, local_only_globs: Sequence[str] = ()) -> Optional[str]:
    if not command or not command.strip():
        return None
    patterns = (*BUILTIN_LOCAL_SCRIPTS, *local_only_globs)
    tokens = _tokens(command)
    for pat in patterns:
        if not pat:
            continue
        if any(fnmatch.fnmatch(tok, pat) or fnmatch.fnmatch(tok.lstrip("./"), pat) or tok.endswith("/" + pat) for tok in tokens):
            return f"command matches local-only script ({pat})"
    if "tmux" in tokens and ("-L" in tokens and ("cloude" in tokens or "carnivore" in tokens)):
        return "command talks to this computer's live tmux server"
    from src.core.pack.jobs.precheck_hook import _programs

    try:
        parts = _programs(command)
    except ValueError:
        parts = []
    for name, _args in parts:
        if name in _LOCAL_DAEMON_PROGRAMS:
            return f"command runs local-only host tool ({name})"
    outside = _outside_project_path(command, project_root)
    if outside is not None:
        return "command accesses paths outside the project folder"
    return None
