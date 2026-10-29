
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.core.inventory.model import DELETE, KEEP, Artifact, SessionIdentity

RECEIPTS_DIR_NAME = "purge-receipts"


class PurgeError(Exception):
    pass


class PurgeRefused(PurgeError):

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class PurgeBusy(PurgeError):
    pass


@dataclass
class PurgePlan:

    session: SessionIdentity
    artifacts: List[Artifact] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    shared_with: List[Dict[str, Any]] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def ok(self) -> bool:
        return not self.blockers

    @property
    def complete(self) -> bool:
        return not any(a.action == KEEP for a in self.artifacts)

    def to_delete(self) -> List[Artifact]:
        return [a for a in self.artifacts if a.action == DELETE]
