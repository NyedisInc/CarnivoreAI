
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict

import structlog

from src.core.automations import lifecycle
from src.core.json_artifact import atomic_write_json

logger = structlog.get_logger()

FILE_NAME = "children.json"


class ChildLedger:

    def __init__(self, state_dir: Path) -> None:
        self._path = Path(state_dir) / "cplugs" / FILE_NAME
        self._lock = threading.Lock()

    def _read(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("cplug_children_unreadable", error_type=type(exc).__name__)
            return {}
        children = data.get("children") if isinstance(data, dict) else None
        return {k: v for k, v in children.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(children, dict) else {}

    def _write(self, children: Dict[str, Dict[str, Any]]) -> None:
        atomic_write_json(self._path, {"children": children}, log_event="cplug_children_write_failed")

    def record(self, plugin_id: str, pid: int) -> bool:
        described = lifecycle.describe_child(pid)
        if described is None:
            return False
        with self._lock:
            children = self._read()
            children[plugin_id] = described
            self._write(children)
        return True

    def forget(self, plugin_id: str) -> None:
        with self._lock:
            children = self._read()
            if children.pop(plugin_id, None) is not None:
                self._write(children)

    def reap(self) -> Dict[str, str]:
        with self._lock:
            children = self._read()
        if not children:
            return {}
        outcome: Dict[str, str] = {}
        for plugin_id, rec in children.items():
            try:
                outcome[plugin_id] = lifecycle.stop_orphan(rec)
            except OSError as exc:
                outcome[plugin_id] = "left"
                logger.warning("cplug_orphan_reap_failed", cplug=plugin_id, error_type=type(exc).__name__)
        with self._lock:
            self._write({})
        return outcome
