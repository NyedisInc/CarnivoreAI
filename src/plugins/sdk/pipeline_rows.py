
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

import structlog

logger = structlog.get_logger()

SCOPE_PLUGIN: str = "plugin"
OUTCOME_OK: str = "ok"
OUTCOME_FAILED: str = "failed"


@dataclass(frozen=True)
class PipelineRow:

    plugin: str
    finished_at: float
    duration_ms: Optional[float]
    runs: Optional[int]
    events: int = 0
    outcome: str = OUTCOME_OK
    error: Optional[str] = None
    seeded: bool = False
    detail: Optional[Dict[str, int]] = None

    def public(self) -> Dict[str, Any]:
        return {"plugin": self.plugin, "kind": "delivery", "scope": SCOPE_PLUGIN, "session_uuid": None, "session": None,
                "project_id": None, "project": None, "conversation_id": None, "family": None, "trigger": None,
                "finished_at": self.finished_at, "duration_ms": self.duration_ms, "runs": self.runs,
                "events": self.events, "outcome": self.outcome, "error": self.error, "seeded": self.seeded,
                "detail": self.detail}


Provider = Callable[[], Sequence[PipelineRow]]
_providers: Dict[str, Provider] = {}


def changed() -> None:
    from src.core.pipeline.engine import push_status

    push_status()


def register(contributor_id: str, provider: Provider) -> None:
    _providers[contributor_id] = provider
    changed()


def unregister(contributor_id: str) -> None:
    if _providers.pop(contributor_id, None) is not None:
        changed()


def rows() -> List[Dict[str, Any]]:
    found: List[tuple] = []
    for contributor_id, provider in list(_providers.items()):
        try:
            found.extend((row, contributor_id) for row in provider())
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("pipeline_rows_provider_failed", contributor=contributor_id, error_type=type(exc).__name__)
    return [{**row.public(), "contributor": contributor} for row, contributor in sorted(found, key=lambda pair: pair[0].finished_at, reverse=True)]


__all__ = ["OUTCOME_FAILED", "OUTCOME_OK", "PipelineRow", "SCOPE_PLUGIN", "changed", "register", "rows", "unregister"]
