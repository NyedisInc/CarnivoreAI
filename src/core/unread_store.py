
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import structlog

from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger()



ROW_KEY_PREFIX = "row:"


class UnreadStore:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
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
        except Exception as exc:
            logger.warning("failed_to_load_unread_state", error=str(exc))

    def _save(self) -> None:
        tmp: Optional[Path] = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = unique_tmp_path(self._path)
            with tmp.open("w") as f:
                json.dump(self._data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(str(tmp), str(self._path))
        except Exception as exc:
            logger.error("failed_to_save_unread_state", error=str(exc))
            # state directory
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass

    @staticmethod
    def compose_key(tmux_name: str, epoch: Optional[int]) -> str:
        """The storage key for one session instance.

        Description: THE KEY IS THE INSTANCE, NOT THE NAME. tmux names are
            reused - kill ``cloude_Infrastructure`` and make another one
            and the new session answers to the same string. Keyed by name
            alone, an unread flag set on the old conversation reappeared on
            the new one, pointing the user at a Stop that happened in a
            session that no longer exists. ``#{session_created}`` is what
            separates the two, and it is the same identity rule
            ``sessions.tmux_created_epoch`` uses everywhere else in this
            codebase, reused rather than re-invented.

            A restart-in-place does NOT move the epoch (measured on tmux
            3.7c: ``respawn-pane -k`` replaces the pane's PROCESS, while
            ``#{session_created}`` belongs to the SESSION), so the flag
            survives exactly the operation the user thinks of as "restart"
            and is dropped exactly when the session is genuinely a new one.

            A ``None`` epoch means the probe could not answer, and that is
            NOT a new instance - it is an unknown one. It composes to the
            bare name, which is also the legacy key shape, so an
            unmeasurable epoch degrades to the old behaviour instead of
            silently minting a second entry for a session that already has
            one.
        Inputs:
            tmux_name: literal tmux session name.
            epoch: ``#{session_created}`` for that instance, or None when
                it could not be measured.
        Output: str - the dict key.
        Example:
            >>> UnreadStore.compose_key("cloude_a", 1757000000)
            'cloude_a@1757000000'
            >>> UnreadStore.compose_key("cloude_a", None)
            'cloude_a'
        """
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
    def is_row_key(key: str) -> bool:
        return key.startswith(ROW_KEY_PREFIX)

    def is_followed_up(
        self,
        row_id: Optional[int],
        tmux_name: Optional[str] = None,
        epoch: Optional[int] = None,
    ) -> bool:
        """Does this session carry a MANUAL follow-up flag?

        Description: the question an asleep row asks (issue #749): its
            pane is gone, so only the reminder the user set can still be
            true of it. Reads the row key, and also the manual half of
            the named instance, so a flag written before the row key
            existed (or while the row could not be read) still answers.
            Never reads the auto half: that one belongs to a pane.
        Inputs:
            row_id: ``sessions.id``, or None.
            tmux_name: the instance's tmux name, or None.
            epoch: the instance's ``#{session_created}``, or None.
        Output: bool.
        Example:
            >>> store.is_followed_up(42, "cloude_a", 1757000000)
            True
        """
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
        """Move an instance-keyed manual flag onto its row, if one is there.

        Description: the migration the sleep runs before it closes a pane
            (issue #749), so a reminder written before this build, or
            while the row could not be read, is not lost with the pane.
            The auto half stays where it is. No flag, no row: no write.
        Inputs: row_id (int | None). tmux_name (str | None). epoch (int |
            None).
        Output: bool - True when a flag was moved.
        """
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

    def prune(self, alive_names: set[str]) -> None:
        dead = {
            key for key in self._data
            if not self.is_row_key(key) and self.name_of(key) not in alive_names
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
