
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Set, Tuple

from src.core.transcript_manifest.scan import Row

MoveKey = Tuple[str, str, str, str, int]


def _key(row: Row) -> MoveKey:
    return (row.family, row.kind, str(row.conversation_id), os.path.basename(row.path), int(row.size))


def _same_file(gone: Row, added: Row) -> bool:
    return not (gone.last_line_uuid and added.last_line_uuid and gone.last_line_uuid != added.last_line_uuid)


def pair_moves(removed: Sequence[Row], added: Sequence[Row]) -> List[Tuple[Row, Row]]:
    waiting: Dict[MoveKey, List[Row]] = {}
    for row in sorted(added, key=lambda r: r.path):
        if row.conversation_id:
            waiting.setdefault(_key(row), []).append(row)
    taken: Set[str] = set()
    pairs: List[Tuple[Row, Row]] = []
    for gone in sorted(removed, key=lambda r: r.path):
        if not gone.conversation_id:
            continue
        match = next((a for a in waiting.get(_key(gone), []) if a.path not in taken and _same_file(gone, a)), None)
        if match is not None:
            taken.add(match.path)
            pairs.append((gone, match))
    return pairs
