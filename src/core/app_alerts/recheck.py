
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.core.app_alerts import kinds


class NoRecheck(LookupError):
    pass


def supports(key: str) -> bool:
    return key.startswith(kinds.RECHECK_PREFIXES)


def run(state_dir: Path, db_path: Path, row: Mapping[str, Any]) -> None:
    key = str(row["key"])
    if key.startswith("backup_health."):
        from src.core.backup_health import runner  # noqa: PLC0415

        runner.run_checks(state_dir, db_path)
        return
    raise NoRecheck(key)
