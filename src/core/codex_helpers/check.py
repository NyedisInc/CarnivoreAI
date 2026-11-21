
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from src.core.codex_helpers import constants as K
from src.core.codex_helpers.handshake import HandshakeResult, probe_host
from src.core.codex_helpers.quarantine import HelperFlag, Reader, read_attribute, read_flag

Identity = Tuple[str, int, int]


@dataclass(frozen=True)
class HelperCheck:

    identity: Identity
    binary: str
    version: Optional[str]
    verdict: str
    helpers: List[HelperFlag] = field(default_factory=list)
    handshake: Optional[HandshakeResult] = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def failing(self) -> bool:
        return self.verdict in K.FAILING

    @property
    def version_label(self) -> str:
        return self.version or os.path.basename(os.path.dirname(os.path.dirname(self.binary))) or "unknown"

    def unapproved_names(self) -> List[str]:
        return [h.name for h in self.helpers if h.unapproved]

    def to_dict(self) -> dict:
        return {"version": self.version, "binary": self.binary, "verdict": self.verdict,
                "failing": self.failing, "unapproved": self.unapproved_names(),
                "helpers": [h.to_dict() for h in self.helpers],
                "handshake": self.handshake.to_dict() if self.handshake else None,
                "checked_at": self.checked_at.isoformat()}


def identity_of(binary: str) -> Optional[Identity]:
    try:
        real = os.path.realpath(binary)
        info = os.stat(real)
    except OSError:
        return None
    return real, info.st_mtime_ns, info.st_size


def judge(helpers: List[HelperFlag], handshake: Optional[HandshakeResult]) -> str:
    if handshake is None:
        return K.NOT_APPLICABLE
    if handshake.answered:
        return K.OK
    return K.BLOCKED if any(h.unapproved for h in helpers) else K.HOST_FAILED


def run_check(
    identity: Identity,
    version: Optional[str],
    *,
    reader: Reader = read_attribute,
    prober: Callable[[str], HandshakeResult] = probe_host,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> HelperCheck:
    binary = identity[0]
    folder = os.path.dirname(binary)
    helpers = [read_flag(name, os.path.join(folder, name), reader) for name in K.HELPER_NAMES
               if os.path.isfile(os.path.join(folder, name))]
    host = os.path.join(folder, K.HOST_NAME)
    handshake = prober(host) if os.path.isfile(host) else None
    return HelperCheck(identity=identity, binary=binary, version=version, verdict=judge(helpers, handshake),
                       helpers=helpers, handshake=handshake, checked_at=clock())
