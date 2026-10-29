
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import structlog

from src.core import config_writer, resource_push, ui_preferences
from src.core.desktop_app import preferences as desktop_preferences
from src.core.resource_push import topics

logger = structlog.get_logger()

COMMITTED = "committed"
"""The change is on disk. ``revision`` is the new one."""

UNCHANGED = "unchanged"
"""Every field sent already held the value that was sent. Nothing was
written and the revision did NOT move, so other clients are not made to
refresh for a change that did not happen."""

STALE_REVISION = "stale_revision"
"""The caller's expected revision is not the current one, so somebody
else committed in between. Nothing was written. ``revision`` and
``values`` describe what is actually stored, which is what the caller
needs to reconcile against."""

REJECTED_INVALID = "rejected_invalid"
"""A field failed validation, or a name is reserved. Nothing was
written and ``detail`` is a plain sentence naming the field."""


class UpdateResult:

    __slots__ = ("status", "revision", "values", "changed", "detail")

    def __init__(
        self,
        status: str,
        revision: int,
        values: Dict[str, Any],
        changed: Optional[Dict[str, Any]] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.status = status
        self.revision = revision
        self.values = values
        self.changed = changed or {}
        self.detail = detail

    def as_payload(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "status": self.status,
            "schema_version": ui_preferences.SCHEMA_VERSION,
            "revision": self.revision,
            "values": self.values,
        }
        if self.changed:
            body["changed"] = self.changed
        if self.detail:
            body["detail"] = self.detail
        return body


class UiPreferencesStore:

    def __init__(self, config_path_provider: Callable[[], Path]) -> None:
        self._path_provider = config_path_provider
        self._guard = threading.Lock()
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_for: Optional[str] = None
        self._generation = 0
        config_writer.on_commit(self._observe_commit)


    def read(self) -> Dict[str, Any]:
        path = self._resolved_path()
        with self._guard:
            if self._cached is not None and self._cached_for == str(path):
                return _copy_block(self._cached)
            generation = self._generation

        block = self._load_from_disk(path)
        with self._guard:
            if generation != self._generation:
                if self._cached is not None and self._cached_for == str(path):
                    return _copy_block(self._cached)
                return _copy_block(block)
            self._cached = block
            self._cached_for = str(path)
            return _copy_block(block)

    def revision(self) -> int:
        return self.read()["revision"]

    def as_result(self) -> UpdateResult:
        block = self.read()
        return UpdateResult(
            status=UNCHANGED, revision=block["revision"], values=block["values"]
        )


    def update(
        self, changes: Dict[str, Any], expected_revision: Optional[int] = None
    ) -> UpdateResult:
        try:
            validated = ui_preferences.validate_changes(changes)
        except ValueError as exc:
            block = self.read()
            return UpdateResult(
                status=REJECTED_INVALID,
                revision=block["revision"],
                values=block["values"],
                detail=str(exc),
            )


        committed: Dict[str, Any] = {}

        def precondition(config: Dict[str, Any]) -> Optional[str]:
            if expected_revision is None:
                return None
            if ui_preferences.revision_of(config) == expected_revision:
                return None
            return config_writer.STALE_REVISION

        def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            new_config, _block, moved = ui_preferences.apply_changes(config, validated)
            if not moved:
                return None
            committed.update(moved)
            return new_config

        outcome = config_writer.commit(
            self._resolved_path(), mutate, precondition=precondition
        )
        block = ui_preferences.read_block(outcome.data)

        if outcome.status == config_writer.STALE_REVISION:
            logger.info(
                "ui_preferences_stale_revision",
                expected=expected_revision,
                current=block["revision"],
                fields=sorted(validated.keys()),
            )
            return UpdateResult(
                status=STALE_REVISION,
                revision=block["revision"],
                values=block["values"],
                detail=(
                    "another device changed these preferences first; "
                    f"the current revision is {block['revision']}"
                ),
            )

        if outcome.status == config_writer.UNCHANGED:
            return UpdateResult(
                status=UNCHANGED, revision=block["revision"], values=block["values"]
            )

        logger.info(
            "ui_preferences_committed",
            revision=block["revision"],
            fields=sorted(committed.keys()),
        )
        if any(desktop_preferences.is_desktop_field(name) for name in committed):
            resource_push.notify(topics.DESKTOP_PREFERENCES)
        return UpdateResult(
            status=COMMITTED,
            revision=block["revision"],
            values=block["values"],
            changed=committed,
        )


    def _observe_commit(self, path: Path, data: Dict[str, Any]) -> None:
        block = ui_preferences.read_block(data)
        with self._guard:
            self._generation += 1
            if str(path) != self._cached_for and self._cached is not None:
                return
            self._cached = block
            self._cached_for = str(path)

    def invalidate(self) -> None:
        with self._guard:
            self._generation += 1
            self._cached = None
            self._cached_for = None

    def _resolved_path(self) -> Path:
        return Path(self._path_provider()).expanduser()

    def _load_from_disk(self, path: Path) -> Dict[str, Any]:
        try:
            config = config_writer.read_config(path)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning(
                "ui_preferences_read_failed", path=str(path), error=str(exc)
            )
            return ui_preferences.empty_block()
        return ui_preferences.read_block(config)


def _copy_block(block: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": block["schema_version"],
        "revision": block["revision"],
        "values": dict(block["values"]),
    }
