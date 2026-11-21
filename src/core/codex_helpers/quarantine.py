
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

import structlog

from src.core.codex_helpers import constants as K

logger = structlog.get_logger(__name__)

Reader = Callable[[str], Optional[str]]


class QuarantineUnreadable(OSError):
    pass


@dataclass(frozen=True)
class HelperFlag:

    name: str
    path: str
    raw: Optional[str]
    approved: Optional[bool]
    readable: bool = True

    @property
    def unapproved(self) -> bool:
        return self.raw is not None and self.approved is False

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.path, "quarantine": self.raw, "approved": self.approved,
                "readable": self.readable}


def parse_flag(text: str) -> Optional[int]:
    head = (text or "").strip().split(";", 1)[0]
    try:
        return int(head, 16)
    except ValueError:
        return None


def read_attribute(path: str) -> Optional[str]:
    try:
        done = subprocess.run([K.XATTR_PATH, "-p", K.QUARANTINE_ATTR, path], capture_output=True, text=True,
                              check=False, timeout=K.XATTR_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise QuarantineUnreadable(str(exc)) from exc
    if done.returncode == 0:
        return done.stdout.strip() or None
    if "No such xattr" in done.stderr:
        return None
    raise QuarantineUnreadable(done.stderr.strip() or f"xattr exited {done.returncode}")


def read_flag(name: str, path: str, reader: Reader = read_attribute) -> HelperFlag:
    try:
        raw = reader(path)
    except QuarantineUnreadable as exc:
        logger.warning("codex_helper_quarantine_unreadable", helper=name, path=path, error=str(exc))
        return HelperFlag(name=name, path=path, raw=None, approved=None, readable=False)
    if raw is None:
        return HelperFlag(name=name, path=path, raw=None, approved=None)
    flag = parse_flag(raw)
    word = raw.split(";", 1)[0].strip()
    if flag is None:
        logger.warning("codex_helper_quarantine_unparseable", helper=name, path=path)
        return HelperFlag(name=name, path=path, raw=word, approved=None)
    return HelperFlag(name=name, path=path, raw=word, approved=bool(flag & K.FLAG_USER_APPROVED))
