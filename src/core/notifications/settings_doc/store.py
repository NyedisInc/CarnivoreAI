
from __future__ import annotations

import secrets as _secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core import config_writer, resource_push
from src.core.notifications import doc_model, types
from src.core.resource_push import topics

log = structlog.get_logger(__name__)

INSTALL_ID_KEY = doc_model.local_key("install_id")
PAUSED_KEY = doc_model.local_key("paused")

Doc = Dict[str, Any]
Mutator = Callable[[Doc, str], Optional[Doc]]


def parse_block(raw: Any) -> Doc:
    if raw is None:
        return {**doc_model.empty_doc(), "rev": 0}
    if (
        not isinstance(raw, dict) or not isinstance(raw.get("global"), dict) or not isinstance(raw.get("local"), dict)
    ):
        log.warning("notification_routing_block_invalid")
        return {**doc_model.empty_doc(), "rev": 0}
    rev = raw.get("rev")
    return {**raw, "rev": rev if isinstance(rev, int) and not isinstance(rev, bool) and rev >= 0 else 0}


def _seed_defaults(doc: Doc, install_id: str) -> Doc:
    if any(p.startswith(doc_model.KIND_DEFAULT + "/") for p in doc["global"]):
        return doc
    seeded = set(types.seed_type_ids())
    for row in types.ordered_types():
        doc = doc_model.set_global(doc, doc_model.default_path(row.id), row.id in seeded, install_id)
    return doc


class SettingsDocStore:

    def __init__(self, config_path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(config_path)
        self._clock = clock
        self._doc: Optional[Doc] = None
        self._lock = threading.Lock()
        self._listeners: List[Callable[[Doc], None]] = []

    def add_listener(self, listener: Callable[[Doc], None]) -> None:
        self._listeners.append(listener)

    def load(self) -> Doc:
        try:
            doc = parse_block(config_writer.read_config(self._path).get(doc_model.BLOCK))
        except (OSError, ValueError):
            log.warning("notification_routing_unreadable")
            doc = parse_block(None)
        with self._lock:
            self._doc = doc
        return doc

    def snapshot(self) -> Doc:
        with self._lock:
            doc = self._doc
        return doc if doc is not None else self.load()

    @property
    def revision(self) -> int:
        return int(self.snapshot()["rev"])

    def install_id(self) -> Optional[str]:
        value = self.snapshot()["local"].get(INSTALL_ID_KEY)
        return value if isinstance(value, str) else None

    def update(self, mutate: Mutator) -> Doc:
        def commit_mutator(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            doc = parse_block(data.get(doc_model.BLOCK))
            me = doc["local"].get(INSTALL_ID_KEY)
            if not isinstance(me, str) or not me:
                me = "n_" + _secrets.token_hex(8)
                doc = doc_model.set_local(doc, INSTALL_ID_KEY, me)
            doc = _seed_defaults(doc, me)
            new = mutate(doc, me)
            if new is None:
                return None
            new = {**new, "global": doc_model.prune_tombstones(new["global"], self._clock()), "rev": doc["rev"] + 1}
            return {**data, doc_model.BLOCK: new}

        outcome = config_writer.commit(self._path, commit_mutator)
        if outcome.status == config_writer.UNCHANGED:
            return self.snapshot()
        if not outcome.wrote:
            raise OSError(f"config write did not land ({outcome.status})")
        written = parse_block(outcome.data.get(doc_model.BLOCK))
        with self._lock:
            self._doc = written
        resource_push.notify(topics.NOTIFICATION_SETTINGS)
        for listener in list(self._listeners):
            try:
                listener(written)
            except Exception as exc:  # noqa: BLE001
                log.warning("notification_routing_listener_failed", error=type(exc).__name__)
        return written
