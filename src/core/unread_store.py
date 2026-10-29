
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Collection, Optional

import structlog

from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger()



ROW_KEY_PREFIX = "row:"


class UnreadStore:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        self._save_lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                logger.warning(
                    "unread_state_unexpected_shape", type=type(raw).__name__
                )
                return
            loaded: dict[str, dict] = {}
            for k, v in raw.items():
                if not isinstance(v, dict):
                    continue
                entry = {
                    "auto": bool(v.get("auto", False)),
                    "manual": bool(v.get("manual", False)),
                }
                if entry["auto"] or entry["manual"]:
                    loaded[str(k)] = entry
            self._data = loaded
            logger.info("unread_state_loaded", count=len(self._data))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("failed_to_load_unread_state", error=str(exc))

    def _save(self) -> None:
        tmp: Optional[Path] = None
        with self._save_lock:
            try:
                snapshot = {k: dict(v) for k, v in list(self._data.items())}
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = unique_tmp_path(self._path)
                with tmp.open("w") as f:
                    json.dump(snapshot, f, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        logger.debug("unread_state_fsync_unsupported")
                os.replace(str(tmp), str(self._path))
            except (OSError, ValueError, TypeError) as exc:
                logger.error("failed_to_save_unread_state", error=str(exc))
                if tmp is not None:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

    @staticmethod
    def compose_key(tmux_name: str, epoch: Optional[int]) -> str:
        return f"{tmux_name}@{int(epoch)}" if epoch is not None else tmux_name

    @staticmethod
    def name_of(key: str) -> str:
        head, sep, tail = key.rpartition("@")
        if sep and tail.isdigit():
            return head
        return key

    @staticmethod
    def row_key(row_id: Optional[int]) -> Optional[str]:
        if row_id is None or isinstance(row_id, bool):
            return None
        try:
            return f"{ROW_KEY_PREFIX}{int(row_id)}"
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _row_id_of(key: str) -> Optional[int]:
        try:
            return int(key[len(ROW_KEY_PREFIX):])
        except ValueError:
            return None

    @staticmethod
    def is_row_key(key: str) -> bool:
        return key.startswith(ROW_KEY_PREFIX)

    def is_followed_up(
        self,
        row_id: Optional[int],
        tmux_name: Optional[str] = None,
        epoch: Optional[int] = None,
    ) -> bool:
        key = self.row_key(row_id)
        if key is not None and self._data.get(key, {}).get("manual"):
            return True
        if not tmux_name:
            return False
        entry = self._lookup(tmux_name, epoch)
        return bool(entry and entry.get("manual"))

    def set_follow_up(
        self,
        row_id: Optional[int],
        tmux_name: Optional[str],
        epoch: Optional[int] = None,
    ) -> None:
        key = self.row_key(row_id)
        if key is None:
            self.set_flag(tmux_name, "manual", True, epoch=epoch)
            return
        self._data[key] = {"auto": False, "manual": True}
        if tmux_name:
            self._drop_instance_manual(tmux_name, epoch)
        self._save()

    def adopt_follow_up(
        self,
        row_id: Optional[int],
        tmux_name: Optional[str],
        epoch: Optional[int] = None,
    ) -> bool:
        key = self.row_key(row_id)
        if key is None or not tmux_name:
            return False
        entry = self._lookup(tmux_name, epoch)
        if not entry or not entry.get("manual"):
            return False
        self._data[key] = {"auto": False, "manual": True}
        self._drop_instance_manual(tmux_name, epoch)
        self._save()
        return True

    def carry_unread_into_row(
        self,
        row_id: Optional[int],
        tmux_name: Optional[str],
        epoch: Optional[int] = None,
    ) -> bool:
        key = self.row_key(row_id)
        if key is None or not tmux_name:
            return False
        entry = self._lookup(tmux_name, epoch)
        if not entry or not (entry.get("auto") or entry.get("manual")):
            return False
        self._data[key] = {"auto": False, "manual": True}
        self._drop_instance_manual(tmux_name, epoch)
        self._save()
        return True

    def _drop_instance_manual(self, tmux_name: str, epoch: Optional[int]) -> None:
        for k in {self.compose_key(tmux_name, epoch), tmux_name}:
            entry = self._data.get(k)
            if entry is None:
                continue
            entry["manual"] = False
            if not entry.get("auto"):
                self._data.pop(k, None)

    def _lookup(self, tmux_name: str, epoch: Optional[int]) -> Optional[dict]:
        entry = self._data.get(self.compose_key(tmux_name, epoch))
        if entry is not None:
            return entry
        return self._data.get(tmux_name)

    def is_unread(
        self,
        tmux_name: str | None,
        epoch: Optional[int] = None,
        row_id: Optional[int] = None,
    ) -> bool:
        key = self.row_key(row_id)
        if key is not None and self._data.get(key, {}).get("manual"):
            return True
        if not tmux_name:
            return False
        entry = self._lookup(tmux_name, epoch)
        if not entry:
            return False
        return bool(entry.get("auto")) or bool(entry.get("manual"))

    def set_flag(
        self,
        tmux_name: str | None,
        field_name: str,
        value: bool,
        epoch: Optional[int] = None,
    ) -> None:
        if not tmux_name:
            return
        key = self.compose_key(tmux_name, epoch)
        entry = self._lookup(tmux_name, epoch) or {"auto": False, "manual": False}
        entry[field_name] = bool(value)
        if key != tmux_name:
            self._data.pop(tmux_name, None)
        if entry["auto"] or entry["manual"]:
            self._data[key] = entry
        else:
            self._data.pop(key, None)
        self._save()

    def clear(
        self,
        tmux_name: str | None,
        epoch: Optional[int] = None,
        row_id: Optional[int] = None,
    ) -> None:
        keys: set[str] = set()
        if tmux_name:
            keys |= {self.compose_key(tmux_name, epoch), tmux_name}
        row = self.row_key(row_id)
        if row is not None:
            keys.add(row)
        if not any(k in self._data for k in keys):
            return
        for key in keys:
            self._data.pop(key, None)
        self._save()

    def prune(
        self,
        alive_names: set[str],
        live_row_ids: Optional[Collection[int]] = None,
    ) -> None:
        dead = {
            key for key in self._data
            if (
                self.name_of(key) not in alive_names
                if not self.is_row_key(key)
                else live_row_ids is not None and self._row_id_of(key) not in live_row_ids
            )
        }
        if not dead:
            return
        logger.info("unread_state_pruning_dead", names=sorted(dead))
        for name in dead:
            self._data.pop(name, None)
        self._save()

    @property
    def raw(self) -> dict[str, dict]:
        return self._data


def live_session_row_ids(
    connect: Callable[[], Optional[sqlite3.Connection]],
) -> Optional[set[int]]:
    conn = connect()
    if conn is None:
        return None
    try:
        return {int(r[0]) for r in conn.execute("SELECT id FROM sessions")}
    except sqlite3.Error as exc:
        logger.warning("unread_live_row_ids_unavailable", error=str(exc))
        return None
    finally:
        conn.close()
