
from __future__ import annotations

import re
import sqlite3
from typing import Mapping, Optional

_NATIVE = re.compile(r'^native_receipt_pending:([0-9a-f]{32})(?::([0-9a-fA-F-]{36}))?$')


def anchor_of(reason: Optional[str]) -> Optional[str]:
    found = _NATIVE.match(reason or '')
    if not found:
        return None
    return f'native:{found.group(1)}:{found.group(2)}' if found.group(2) else f'native:{found.group(1)}'


def header_of(message: Mapping) -> str:
    from src.core.crosstalk.delivery.dispatcher import envelope

    return envelope(dict(message)).split('\n', 1)[0]


def stamp(conn: sqlite3.Connection, prior: Mapping, now: float) -> None:
    try:
        header: Optional[str] = header_of(prior)
    except (KeyError, TypeError):
        header = None
    anchor = anchor_of(prior['reason'])
    conn.execute('UPDATE crosstalk_messages SET landed_session_id=?, landed_at=?, landed_header=?, landed_anchor=?, delivery_path=? WHERE id=?',
                 (prior['receiver_id'], now, header, anchor, 'native' if anchor else 'paste', prior['id']))
