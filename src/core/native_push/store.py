"""Native push devices, one JSON file in the state directory (0600).

A row is an APNs device token (platform ``ios``) bound to ONE paired link device. ``device_id`` is set server-side
only, from the link gate's verified device (never from a request body). The per-phone AES-256-GCM payload key is NOT
here: it lives in the login Keychain under its own service (``wiring.secrets_for``, apart from the notification
destination secrets), under the row's own id, which has the destination id shape ``d_`` plus 12 lowercase hex characters.
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

FILE_NAME = "native_push_devices.json"
MAX_DEVICES_PER_LINK_DEVICE = 5
_REQUIRED = ("id", "token", "environment", "device_id")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NativeDeviceStore:

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
            logger.warning("native_push_store_unreadable", error_type=type(exc).__name__)
            return []
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in _REQUIRED)]

    def _save(self, rows: List[Dict[str, Any]]) -> None:
        atomic_write(self._path, json.dumps(rows), mode=0o600)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._load()

    def upsert(self, device_id: str, platform: str, token: str, environment: str, bundle_id: str,
               app_version: str) -> tuple[Dict[str, Any], bool]:
        with self._lock:
            rows = self._load()
            now = now_iso()
            for row in rows:
                if row["device_id"] == device_id and row["token"] == token:
                    row.update(platform=platform, environment=environment, bundle_id=bundle_id,
                               app_version=app_version, last_seen=now)
                    self._save(rows)
                    return dict(row), False
            if sum(1 for r in rows if r["device_id"] == device_id) >= MAX_DEVICES_PER_LINK_DEVICE:
                raise OverflowError("too many native devices for this phone")
            taken = {r["id"] for r in rows}
            new_id = "d_" + secrets.token_hex(6)
            while new_id in taken:
                new_id = "d_" + secrets.token_hex(6)
            row = {"id": new_id, "platform": platform, "token": token, "environment": environment,
                   "bundle_id": bundle_id, "app_version": app_version, "device_id": device_id,
                   "created_at": now, "last_seen": now, "last_result": None}
            rows.append(row)
            self._save(rows)
            return dict(row), True

    def record_result(self, row_id: str, status: int, *, at: Optional[str] = None) -> None:
        with self._lock:
            rows = self._load()
            for row in rows:
                if row["id"] == row_id:
                    row["last_result"] = {"status": status, "at": at or now_iso()}
                    self._save(rows)
                    return

    def remove(self, row_id: str) -> bool:
        with self._lock:
            rows = self._load()
            kept = [r for r in rows if r["id"] != row_id]
            if len(kept) != len(rows):
                self._save(kept)
            return len(kept) != len(rows)

    def remove_for_device(self, device_id: str) -> List[str]:
        if not device_id:
            return []
        with self._lock:
            rows = self._load()
            gone = [r["id"] for r in rows if r["device_id"] == device_id]
            if gone:
                self._save([r for r in rows if r["device_id"] != device_id])
            return gone


def public_view(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("id", "platform", "environment", "bundle_id", "app_version", "device_id", "created_at", "last_seen",
            "last_result")
    return {k: row.get(k) for k in keys}
