
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from src.core.attention_history.recorder import EdgeRecorder, resolve_from_datastore
from src.core.attention_history.store import DB_NAME, AttentionHistoryStore


def build_recorder(state_dir: Callable[[], Path]) -> EdgeRecorder:
    from src.core.db import db_path_for  # noqa: PLC0415
    from src.core.session_timeline import push  # noqa: PLC0415

    def submit(fn: Callable[..., None], *args: object) -> None:
        asyncio.get_running_loop().run_in_executor(None, fn, *args)

    def resolve(session_id: str, key: str):
        return resolve_from_datastore(db_path_for(state_dir()), key, session_id)

    store = AttentionHistoryStore(lambda: Path(state_dir()) / DB_NAME)
    return EdgeRecorder(store, resolve, submit=submit, announce=push.announce_attention)
