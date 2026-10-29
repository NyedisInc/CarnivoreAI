
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from src.cplugs.sdk import ports

PORT = "save.restore_points"


class NoRestorePoint(LookupError):
    pass


class RestoreFailed(RuntimeError):
    pass


class RestorePointsPort(Protocol):

    def list_points(self, conversation_id: str) -> List[Dict[str, Any]]:
        pass

    def restore_newest(self, conversation_id: str, corpus_root: Path) -> Path:
        pass


def get() -> Optional[RestorePointsPort]:
    return ports.get(PORT)


__all__ = ["NoRestorePoint", "PORT", "RestoreFailed", "RestorePointsPort", "get"]
