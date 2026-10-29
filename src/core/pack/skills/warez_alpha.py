
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import structlog

from src.core.pack.skills import rules
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.core.skills.records import SIDECAR_NAME

logger = structlog.get_logger()

REASON_EDITED = "edited after install on alpha, not synced"
REASON_OTHER_NAME = "installed under another name on alpha, not synced"
REASON_INCOMPLETE = "catalog record incomplete"
REASON_NO_RECORD = "catalog folder with no install record"
KINDS = ("skill", "plugin")

Pair = tuple[str, str]


@dataclass
class WarezPlan:

    entries: list[list[str]] = field(default_factory=list)
    held: list[list[str]] = field(default_factory=list)
    pairs: set[Pair] = field(default_factory=set)


def _unedited(row: Any, folder: Path) -> bool:
    from src.core.skill_watch.measure import TooLarge
    from src.core.skill_watch.sentinel import measure_folder

    try:
        return measure_folder(folder)[0] == row.digest
    except (TooLarge, OSError) as exc:
        logger.info("pack_warez_measure_unreadable", error=type(exc).__name__)
        return False


def plan(services: Any, roots: Mapping[str, Path]) -> WarezPlan:
    out, real = WarezPlan(), {family: os.path.realpath(root) for family, root in roots.items()}
    rows: dict[Pair, Any] = {}
    forked: frozenset = frozenset()
    if services is not None:
        with services.catalog.ledger() as ledger:
            forked = ledger.forked_ids()
            for row in ledger.list():
                if row.scope != SCOPE_GLOBAL or row.kind not in KINDS:
                    continue
                for target in ledger.targets(row.install_id):
                    path = Path(target.path)
                    if target.harness in real and os.path.realpath(path.parent) == real[target.harness]:
                        rows[(target.harness, path.name)] = row
    for family, root in sorted(roots.items()):
        try:
            names = {e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False)}
        except OSError:
            continue
        for folder in sorted(names):
            row, pair = rows.get((family, folder)), (family, folder)
            has_sidecar = os.path.lexists(root / folder / SIDECAR_NAME)
            if (row is None and not has_sidecar) or rules.skill_name_problem(folder) is not None:
                continue
            out.pairs.add(pair)
            if row is None:
                out.held.append([family, folder, REASON_NO_RECORD])
            elif row.install_id in forked or not _unedited(row, root / folder):
                out.held.append([family, folder, REASON_EDITED])
            elif folder != row.name:
                out.held.append([family, folder, REASON_OTHER_NAME])
            elif row.consented_body_sha is None:
                out.held.append([family, folder, REASON_INCOMPLETE])
            else:
                out.entries.append([family, folder, row.item_id, row.kind, row.version, row.digest, row.consented_body_sha])
    return out


def map_digest(entry: list[str]) -> Optional[str]:
    return entry[5] if len(entry) == 7 else None
