
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.deepsearch import constants as K
from src.core.deepsearch import grouped, status

PROMPT_KINDS: tuple = (K.KIND_USER,)


def search_prompts(conn: sqlite3.Connection, state_dir: Path, query: str, *, project: Optional[str] = None,
                   limit: int = grouped.GROUP_LIMIT_DEFAULT, offset: int = 0,
                   per_group: int = grouped.PER_GROUP_DEFAULT, sort: str = grouped.SORT_RELEVANCE) -> Dict[str, Any]:
    answer = grouped.search_grouped(conn, state_dir, query, kinds=PROMPT_KINDS, project=project, limit=limit,
                                    offset=offset, per_group=per_group, sort=sort)
    answer["ingest"] = status.index_status(state_dir)
    return answer
