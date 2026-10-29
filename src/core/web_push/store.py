"""Push subscriptions, one JSON file in the state directory (0600: it holds each subscription's auth secret).

A subscription belongs to the authenticated owner (every route is owner only). ``device_id`` is optional and
is set server-side only (never from a client body): the push route passes the link gate's verified device id for a
subscription made over the phone link, so revoking that device calls :meth:`SubscriptionStore.remove_for_device`.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.config_files_io import atomic_write

logger = structlog.get_logger()

FILE_NAME = "web_push_subscriptions.json"
MAX_SUBSCRIPTIONS = 20


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SubscriptionStore:

    def __init__(self, state_dir: Path) -> None:
        """Input: the state directory. The file is created on the first write."""
        self._path = Path(state_dir) / FILE_NAME
        self._lock = threading.Lock()

    def _load(self) -> List[Dict[str, Any]]:
        try:
            rows = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            logger.warning("web_push_store_unreadable", error_type=type(exc).__name__)
            return []
        if not isinstance(rows, list):
            return []
        need = ("id", "endpoint", "p256dh", "auth")
        return [r for r in rows if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in need)]

    def _save(self, rows: List[Dict[str, Any]]) -> None:
        atomic_write(self._path, json.dumps(rows), mode=0o600)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._load()

    def add(self, endpoint: str, p256dh: str, auth: str, device_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            rows = self._load()
            for row in rows:
                if row.get("endpoint") == endpoint:
                    row.update(p256dh=p256dh, auth=auth, device_id=device_id)
                    self._save(rows)
                    return dict(row)
            if len(rows) >= MAX_SUBSCRIPTIONS:
                raise OverflowError("too many push subscriptions")
            row = {"id": secrets.token_urlsafe(9), "endpoint": endpoint, "p256dh": p256dh, "auth": auth,
                   "device_id": device_id, "created_at": now_iso(), "last_result": None}
            rows.append(row)
            self._save(rows)
            return dict(row)

    def remove(self, sub_id: str) -> bool:
        with self._lock:
            rows = self._load()
            kept = [r for r in rows if r.get("id") != sub_id]
            if len(kept) != len(rows):
                self._save(kept)
            return len(kept) != len(rows)

    def remove_for_device(self, device_id: str) -> int:
        if not device_id:
            return 0
        with self._lock:
            rows = self._load()
            kept = [r for r in rows if r.get("device_id") != device_id]
            if len(kept) != len(rows):
                self._save(kept)
            return len(rows) - len(kept)

    def record_result(self, sub_id: str, status: int, *, at: Optional[str] = None) -> None:
        with self._lock:
            rows = self._load()
            for row in rows:
                if row.get("id") == sub_id:
                    row["last_result"] = {"status": status, "at": at or now_iso()}
                    self._save(rows)
                    return


def public_view(row: Dict[str, Any]) -> Dict[str, Any]:
    from src.core.web_push.endpoints import host_of

    return {"id": row["id"], "service": host_of(row["endpoint"]), "device_id": row.get("device_id"),
            "created_at": row.get("created_at"), "last_result": row.get("last_result")}
