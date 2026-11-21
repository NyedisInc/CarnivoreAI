
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

import structlog

from src.core.pipeline import contract as C

logger = structlog.get_logger(__name__)

COMPILED_IN_TIERS: Tuple[str, ...] = ("builtin", "core")

_read_failure_logged: set = set()


def is_on(plugin: C.Plugin, state_dir: Path) -> bool:
    if plugin.switch_id is None:
        return True
    return _feature_on(plugin.switch_id, state_dir)


def _feature_on(feature_id: str, state_dir: Path) -> bool:
    from src.plugins.host import gate, runtime  # noqa: PLC0415

    try:
        definition = next((d for d in runtime.definitions() if d.id == feature_id), None)
        if definition is None or definition.manifest.tier not in COMPILED_IN_TIERS:
            return False
        return gate.is_on(feature_id, state_dir)
    except (runtime.RegistryError, OSError, ValueError, KeyError) as exc:
        if feature_id not in _read_failure_logged:
            _read_failure_logged.add(feature_id)
            logger.error("pipeline_switch_unreadable", feature=feature_id, error=f"{type(exc).__name__}: {exc}")
        return False


def active(plugins: Sequence[C.Plugin], state_dir: Path) -> Tuple[C.Plugin, ...]:
    return tuple(p for p in plugins if is_on(p, state_dir))
