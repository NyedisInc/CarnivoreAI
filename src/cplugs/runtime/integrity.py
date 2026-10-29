
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


SIDECAR_NAME = ".carnivore-skill.json"


class IntegrityError(Exception):
    pass


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    base = Path(root)
    for path in sorted(base.rglob("*")):
        try:
            st = path.lstat()
        except OSError as exc:
            raise IntegrityError(f"{path}: {exc}") from exc
        if path.name == SIDECAR_NAME and path.parent == base and stat.S_ISREG(st.st_mode):
            continue
        if stat.S_ISLNK(st.st_mode) or not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
            raise IntegrityError(f"{path}: not a regular file or folder")
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            raise IntegrityError(f"{path}: bytecode in the code root (it would run instead of the reviewed source)")
        rel = path.relative_to(base).as_posix()
        if stat.S_ISDIR(st.st_mode):
            digest.update(b"D\0" + rel.encode("utf-8") + b"\0")
            continue
        flags = os.O_RDONLY | os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise IntegrityError(f"{path}: {exc}") from exc
        digest.update(b"F\0" + rel.encode("utf-8") + b"\0" + (b"x" if st.st_mode & stat.S_IXUSR else b"-") + hashlib.sha256(data).digest())
    return digest.hexdigest()
