
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Iterable, Tuple

EXPORT_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")
MAX_EXPORT_BYTES = 8 * 1024 * 1024
_DENIED_HOME_PARTS = ("Library", ".ssh", ".aws", ".gnupg", ".config", ".zshrc", ".zprofile", ".zshenv", ".bashrc",
                      ".bash_profile", ".profile", ".claude", ".codex", ".carnivore", ".local/bin", "bin")
_AGENT_INSTRUCTION_NAMES = frozenset({"claude.md", "agents.md", "gemini.md"})
_DENIED_ABSOLUTE = ("/Applications", "/System", "/Library", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/var/root")


class UnsafePath(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def open_contained(root: Path, relative: str, flags: int, mode: int = 0o600) -> int:
    parts = [p for p in relative.split("/") if p not in ("", ".")]
    if not parts or relative.startswith("/") or ".." in parts or "\x00" in relative:
        raise UnsafePath("escapes", "path leaves the folder")
    directory = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in parts[:-1]:
            try:
                nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except OSError as exc:
                if exc.errno in (40, 62, 20):
                    raise UnsafePath("symlink", name) from exc
                raise
            os.close(directory)
            directory = nxt
        try:
            return os.open(parts[-1], flags | os.O_NOFOLLOW, mode, dir_fd=directory)
        except OSError as exc:
            if exc.errno in (40, 62):
                raise UnsafePath("symlink", parts[-1]) from exc
            raise
    finally:
        os.close(directory)


def tree_usage(root: Path) -> Tuple[int, int]:
    total = count = 0
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    st = entry.stat(follow_symlinks=False)
                    count += 1
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(entry.path)
                    else:
                        total += st.st_size
        except FileNotFoundError:
            continue
    return total, count


def check_export_name(name: object) -> str:
    if not isinstance(name, str) or not EXPORT_NAME.match(name) or name in (".", ".."):
        raise UnsafePath("bad_name", "an export name is a plain basename with no leading dot")
    if name.lower() in _AGENT_INSTRUCTION_NAMES:
        raise UnsafePath("bad_name", "CLAUDE.md, AGENTS.md and GEMINI.md are read by agents as instructions")
    return name


def check_export_folder(folder: object, home: Path, picked: Iterable[Path]) -> Path:
    if not isinstance(folder, str) or not folder or "\x00" in folder:
        raise UnsafePath("bad_folder", "a folder is required")
    real = Path(os.path.realpath(folder))
    allowed = {Path(os.path.realpath(p)) for p in picked}
    if real not in allowed:
        raise UnsafePath("bad_folder", "not a folder the owner picked for this plugin")
    home_real = Path(os.path.realpath(home))
    if real == home_real or real == Path("/"):
        raise UnsafePath("bad_folder", "the home folder itself is not an export target")
    for part in _DENIED_HOME_PARTS:
        base = home_real / part
        if real == base or base in real.parents:
            raise UnsafePath("bad_folder", f"~/{part} is not an export target")
    for prefix in _DENIED_ABSOLUTE:
        base = Path(prefix)
        if real == base or base in real.parents:
            raise UnsafePath("bad_folder", f"{prefix} is not an export target")
    if not real.is_dir():
        raise UnsafePath("bad_folder", "not a directory")
    return real


def write_export(folder: Path, name: str, data: bytes) -> Path:
    check_export_name(name)
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError("export too large")
    fd = open_contained(folder, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
    return folder / name
