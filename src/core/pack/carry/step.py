
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Collection, Dict, Optional

from src.core.pack.carry import scan, send
from src.core.pack.migrate.plan import MigrateError, Request

_REASONS = {"machine_unreachable": "is not connected right now", "runs_older_carnivore": "runs an older carnivore"}


def carried_ok(result: Optional[Dict[str, Any]]) -> bool:
    return result is None or bool(result.get("sent")) or result.get("reason") == "nothing_new"


def failure(label: str, result: Dict[str, Any], step: str) -> MigrateError:
    code = str(result.get("error") or "unknown")
    why = f"{label} {_REASONS[code]}" if code in _REASONS else f"it failed ({code})"
    return MigrateError("carry_failed", f"the project's commits did not reach {label}: {why}; fix that, then send again", 502, step)


@dataclass
class CodeStep:

    root: str
    air_gap: bool
    label: str
    target_caps: Collection[str]
    carry_commits: Callable[[], Awaitable[Dict[str, Any]]]
    found: Optional[scan.CarrySet] = None
    moved: Dict[str, str] = field(default_factory=dict)
    request: Optional[Request] = None
    project_uid: str = ""
    outbox: str = ""
    op_id: str = field(default_factory=lambda: "carry-" + os.urandom(6).hex())

    @property
    def units_ok(self) -> bool:
        return scan.CARRY_TREE in self.target_caps and self.request is not None and bool(self.project_uid and self.outbox)

    async def gate(self) -> scan.CarrySet:
        self.found = await asyncio.to_thread(scan.scan_project, self.root, air_gap=self.air_gap)
        refusal = scan.blockers(self.found, self.label, self.target_caps)
        if refusal is not None:
            raise MigrateError(refusal[0], refusal[1], 409, "check")
        if self.units_ok:
            await send.check_units(self.request, self.found, self.project_uid, self.label)
        return self.found

    async def carry(self) -> Dict[str, Any]:
        if self.found is None:
            return {}
        result: Dict[str, Any] = {}
        if self.found.root_is_repo:
            result = await self.carry_commits()
            if not carried_ok(result):
                raise failure(self.label, result, "code")
        if self.units_ok:
            rows = await send.send_units(self.request, self.found, project_uid=self.project_uid, op_id=self.op_id, outbox=self.outbox, air_gap=self.air_gap, label=self.label)
            self.moved = {src: to for row in rows if row.get("kind") == "worktree" for src, to in (row.get("paths") or {}).items()}
            result = {**result, "units": rows}
        return result
