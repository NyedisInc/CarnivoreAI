
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CONV = "506255af-59a3-4ba0-877e-724bae1f682b"
PROJECT_DIR = "-tmp-timer-fixture"
WORKDIR = "/tmp/timer-fixture"
VERSION = "2.1.181"


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 27, hour, minute, second, tzinfo=timezone.utc)


def ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _envelope(kind: str, moment: datetime, n: int) -> Dict[str, Any]:
    return {
        "parentUuid": f"00000000-0000-4000-8000-{n:012d}",
        "isSidechain": False,
        "userType": "external",
        "cwd": WORKDIR,
        "sessionId": CONV,
        "version": VERSION,
        "gitBranch": "master",
        "type": kind,
        "uuid": f"10000000-0000-4000-8000-{n:012d}",
        "timestamp": ts(moment),
    }


class Transcript:

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def _add(self, record: Dict[str, Any]) -> None:
        self.records.append(record)

    def prompt(self, moment: datetime, text: str = "placeholder prompt", meta: bool = False) -> None:
        record = _envelope("user", moment, len(self.records))
        record["message"] = {"role": "user", "content": text}
        if meta:
            record.update(isMeta=True, promptId="20000000-0000-4000-8000-000000000001",
                          permissionMode="default")
        self._add(record)

    def call(self, moment: datetime, tool: str, tool_use_id: str, payload: Dict[str, Any]) -> None:
        record = _envelope("assistant", moment, len(self.records))
        record["message"] = {
            "role": "assistant", "model": "claude-placeholder", "type": "message",
            "content": [{"type": "tool_use", "id": tool_use_id, "name": tool, "input": payload}],
        }
        self._add(record)

    def result(self, moment: datetime, tool_use_id: str, text: str, tool_use_result: Any) -> None:
        record = _envelope("user", moment, len(self.records))
        record["message"] = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}]}
        if tool_use_result is not None:
            record["toolUseResult"] = tool_use_result
        self._add(record)

    def wakeup(self, moment: datetime, tool_use_id: str, delay: int,
               prompt: str = "check the placeholder job", reason: str = "placeholder reason",
               stop: Optional[bool] = None, answer: bool = True) -> None:
        payload: Dict[str, Any] = {"delaySeconds": delay, "reason": reason, "prompt": prompt}
        if stop is not None:
            payload["stop"] = stop
        self.call(moment, "ScheduleWakeup", tool_use_id, payload)
        if answer:
            fire = int(moment.timestamp() * 1000) + delay * 1000
            self.result(moment, tool_use_id,
                        f"Next wakeup scheduled for 00:00:00 (in {delay}s).",
                        {"scheduledFor": fire, "clampedDelaySeconds": delay, "wasClamped": False})

    def cron(self, moment: datetime, tool_use_id: str, job: str, expression: str,
             recurring: Optional[bool] = True, days: int = 7,
             prompt: str = "placeholder cron prompt") -> None:
        payload: Dict[str, Any] = {"cron": expression, "prompt": prompt}
        if recurring is not None:
            payload["recurring"] = recurring
        self.call(moment, "CronCreate", tool_use_id, payload)
        if recurring is False:
            text = (f"Scheduled one-shot task {job} ({expression}). Session-only (not written "
                    "to disk, dies when Claude exits). It will fire once then auto-delete.")
        else:
            text = (f"Scheduled recurring job {job} (Every 5 minutes). Session-only (not written "
                    f"to disk, dies when Claude exits). Auto-expires after {days} days. "
                    "Use CronDelete to cancel sooner.")
        self.result(moment, tool_use_id, text, {
            "id": job, "humanSchedule": "Every 5 minutes" if recurring is not False else expression,
            "recurring": recurring is not False, "durable": False})

    def cron_delete(self, moment: datetime, tool_use_id: str, job: str) -> None:
        self.call(moment, "CronDelete", tool_use_id, {"id": job})
        self.result(moment, tool_use_id, f"Cancelled job {job}.", {"id": job})

    def text(self) -> str:
        return "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in self.records)

    def write(self, projects_dir: Path) -> Path:
        folder = projects_dir / PROJECT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{CONV}.jsonl"
        path.write_text(self.text(), encoding="utf-8")
        return path
