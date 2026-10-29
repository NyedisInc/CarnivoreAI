
from __future__ import annotations

import time
from typing import Any, Set

from src.cplugs.huddle import rules
from src.cplugs.huddle.cards import tx


def mark(store: Any, item_id: int) -> bool:
    touched: Set[str] = set()
    now = time.time()
    with tx.write(store, touched) as conn:
        row = conn.execute("SELECT list_key FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE work_items SET phone_sent_at = ? WHERE id = ?", (now, item_id))
        tx.bump(conn, item_id, rules.CLAUDE, now)
        touched.add(row[0])
    return True
