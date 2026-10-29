
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional, Sequence

from src.cplugs.crate import constants as K


class NameTaken(Exception):

    def __init__(self, path: str) -> None:
        super().__init__(f"{path} already exists")
        self.path = path


def fsync_dir(folder: Path) -> None:
    fd = os.open(str(folder), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(temp: Path, final: Path) -> None:
    try:
        os.link(temp, final)
        linked = True
    except FileExistsError as exc:
        raise NameTaken(str(final)) from exc
    except OSError:
        _reserve(final)
        linked = False
    try:
        if linked:
            os.unlink(temp)
        else:
            os.rename(temp, final)
        fsync_dir(final.parent)
    except BaseException:
        if os.path.lexists(final):
            os.unlink(final)
        raise


def _reserve(final: Path) -> None:
    try:
        fd = os.open(final, os.O_CREAT | os.O_EXCL | os.O_WRONLY, K.FILE_MODE)
    except FileExistsError as exc:
        raise NameTaken(str(final)) from exc
    os.close(fd)


def write_new(final: Path, data: bytes, on_temp: Optional[Callable[[str], None]] = None) -> None:
    temp = final.parent / f".{final.name}.partial"
    if on_temp is not None:
        on_temp(str(temp))
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, K.FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        publish(temp, final)
    finally:
        if temp.exists():
            os.unlink(temp)


def sha_sidecar(sha256: str, name: str) -> bytes:
    return f"{sha256}  {name}\n".encode("ascii")


def age_readme(name: str, recipients: Sequence[str], key_hint: str) -> bytes:
    lines = [f"{name} is an encrypted crate (age v1, X25519).", "",
             "it opens with the private key of one of these age recipients:"]
    lines += [f"  {r}" for r in recipients]
    if key_hint.strip():
        lines += ["", f"where the key lives: {key_hint.strip()}"]
    lines += ["", "decrypt it with:", f"  age -d -i <identity file> {name} > crate.crate", "",
              "then read crate.crate's README.txt, or run: python3 -m src.core.crate_format verify crate.crate", ""]
    return "\n".join(lines).encode("utf-8")
