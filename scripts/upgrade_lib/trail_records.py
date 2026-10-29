#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_FIELDS = ("entry_uuid", "kind", "status", "started_at")

READ_OK = "ok"
READ_ABSENT = "absent"
READ_UNREADABLE = "unreadable"


class Step:

    def __init__(self, first: Dict[str, Any]) -> None:
        self.entry_uuid = first["entry_uuid"]
        self.kind = first["kind"]
        self.started_at = first["started_at"]
        self.from_version = first.get("from_version")
        self.to_version = first.get("to_version")
        self.status = first.get("status")
        self.completed_at = first.get("completed_at")
        self.backup_path = first.get("backup_path")
        self.backup_verified = first.get("backup_verified")
        self.app_version = first.get("app_version")

    def merge(self, line: Dict[str, Any]) -> None:
        for attr in (
            "from_version", "to_version", "completed_at", "backup_path",
            "backup_verified", "app_version",
        ):
            value = line.get(attr)
            if value is not None:
                setattr(self, attr, value)
        status = line.get("status")
        if status:
            self.status = status
        started = line.get("started_at")
        if started and started < self.started_at:
            self.started_at = started

    @property
    def has_verified_backup(self) -> bool:
        return bool(self.backup_path) and self.backup_verified in (1, True)


def _parse_line(raw: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for field_name in REQUIRED_FIELDS:
        if data.get(field_name) in (None, ""):
            return None
    return data


def read_steps(path: Path) -> Tuple[str, List[Step], Optional[str], Optional[int]]:
    if not path.exists():
        return READ_ABSENT, [], f"{path} does not exist", None
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        return READ_UNREADABLE, [], f"could not read {path}: {exc}", None
    except UnicodeDecodeError as exc:
        return READ_UNREADABLE, [], f"{path} is not valid UTF-8: {exc}", None

    ends_cleanly = text.endswith("\n") or text == ""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]

    steps: Dict[str, Step] = {}
    last_index = len(lines) - 1
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        parsed = _parse_line(stripped)
        if parsed is None:
            if index == last_index and not ends_cleanly:
                continue
            return (
                READ_UNREADABLE,
                [],
                f"{path.name} is corrupt at line {index + 1}: the line is "
                "not a JSON object carrying entry_uuid, kind, status and "
                "started_at",
                index + 1,
            )
        uuid = parsed["entry_uuid"]
        if uuid in steps:
            steps[uuid].merge(parsed)
        else:
            steps[uuid] = Step(parsed)

    ordered = sorted(steps.values(), key=lambda s: (s.started_at, s.entry_uuid))
    return READ_OK, ordered, None, None
