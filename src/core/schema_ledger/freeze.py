
from __future__ import annotations

from pathlib import Path

from src.core.schema_ledger.errors import FreezeViolation, LedgerFormatError


def read_freeze(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerFormatError(f"{path}: cannot read the freeze marker ({exc})") from exc
    for line in text.splitlines():
        if line.startswith("frozen_rungs "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError) as exc:
                raise LedgerFormatError(f"{path}: bad frozen_rungs line {line!r}") from exc
    raise LedgerFormatError(f"{path}: no 'frozen_rungs <n>' line")


def check_freeze(name: str, marker: Path, rung_count: int, pointer: str) -> None:
    frozen = read_freeze(marker)
    if rung_count != frozen:
        raise FreezeViolation(
            f"the {name} ladder is frozen at {frozen} rungs and the code has {rung_count}. No new {name} rung may land "
            f"until the split reaches the phase that lifts the freeze (issue #1711; {pointer}). If this change really "
            f"must add a rung, update {marker.name} in the same commit and say why in the commit message.")
