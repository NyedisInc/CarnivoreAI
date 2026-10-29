
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from src.core.attention_history.recorder import EdgeRecorder, resolve_from_datastore
from src.core.attention_history.store import DB_NAME, AttentionHistoryStore


def build_recorder(state_dir: Callable[[], Path]) -> EdgeRecorder:
    """The recorder the attention watcher is wired to. Inputs: state_dir - read lazily. Output: EdgeRecorder.

    Description: the state directory is read when an event is written, not at construction, the way the watcher's
      other state-dir readers do it. Writes go to the default executor so the event loop never opens sqlite, and each
      one that changed the file tells open timelines (coalesced, existing ``session_timeline`` topic).
    Example: watcher_kwargs["on_transition"] = build_recorder(settings.get_state_dir).on_transition
    """
    from src.core.db import db_path_for  # noqa: PLC0415
    from src.core.session_timeline import push  # noqa: PLC0415

    def submit(fn: Callable[..., None], *args: object) -> None:
        asyncio.get_running_loop().run_in_executor(None, fn, *args)

    def resolve(session_id: str, key: str):
        return resolve_from_datastore(db_path_for(state_dir()), key, session_id)

    store = AttentionHistoryStore(lambda: Path(state_dir()) / DB_NAME)
    return EdgeRecorder(store, resolve, submit=submit, announce=push.announce_attention)
