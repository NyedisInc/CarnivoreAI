
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

KIND_INTERACTIVE = "interactive"

KIND_AUTOMATED = "automated"

KIND_UNKNOWN = "unknown"

SESSION_KINDS = (KIND_INTERACTIVE, KIND_AUTOMATED, KIND_UNKNOWN)

SCHEDULED_TASK_TAG = "<scheduled-task"

INTERACTIVE_ENTRYPOINTS = frozenset({"cli", "claude-desktop"})

HEADLESS_ENTRYPOINT = "sdk-cli"

INTERACTIVE_RECORD_TYPES = frozenset(
    {"custom-title", "mode", "permission-mode"}
)

MAX_RECORDS_SCANNED = 400

MARKER_SCHEDULER_TAG = "scheduler_tag"
MARKER_HEADLESS_ENTRYPOINT = "headless_entrypoint"
MARKER_INTERACTIVE_ENTRYPOINT = "interactive_entrypoint"
MARKER_PLAN_APPROVED = "plan_approved"
MARKER_TUI_RECORD = "tui_record"
MARKER_NONE = "no_marker"
MARKER_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class KindVerdict:

    kind: str
    marker: str
    detail: str


def _record_text(record: Dict[str, Any]) -> str:
    content = record.get("content")
    if isinstance(content, str):
        return content
    message = record.get("message")
    if isinstance(message, dict):
        inner = message.get("content")
        if isinstance(inner, str):
            return inner
        if isinstance(inner, list):
            return " ".join(
                block.get("text", "")
                for block in inner
                if isinstance(block, dict)
            )
    return ""


@dataclass
class _Evidence:

    scheduler_tag: bool = False
    entrypoints: Set[str] = None  # type: ignore[assignment]
    plan_content: bool = False
    tui_record: Optional[str] = None

    def __post_init__(self) -> None:
        if self.entrypoints is None:
            self.entrypoints = set()


def _gather(records: Iterable[Dict[str, Any]]) -> _Evidence:
    found = _Evidence()
    for index, record in enumerate(records):
        if index >= MAX_RECORDS_SCANNED:
            break
        if not isinstance(record, dict):
            continue
        if not found.scheduler_tag:
            text = _record_text(record)
            if text.lstrip().startswith(SCHEDULED_TASK_TAG):
                found.scheduler_tag = True
        entrypoint = record.get("entrypoint")
        if isinstance(entrypoint, str) and entrypoint:
            found.entrypoints.add(entrypoint)
        if "planContent" in record:
            found.plan_content = True
        record_type = record.get("type")
        if (
            found.tui_record is None
            and isinstance(record_type, str)
            and record_type in INTERACTIVE_RECORD_TYPES
        ):
            found.tui_record = record_type
    return found


def classify_records(records: Iterable[Dict[str, Any]]) -> KindVerdict:
    found = _gather(records)
    if found.scheduler_tag:
        return KindVerdict(
            KIND_AUTOMATED,
            MARKER_SCHEDULER_TAG,
            "the prompt is wrapped in a <scheduled-task> tag, which only "
            "Claude Code's scheduler writes",
        )
    if found.entrypoints:
        if found.entrypoints & INTERACTIVE_ENTRYPOINTS:
            entry = sorted(found.entrypoints & INTERACTIVE_ENTRYPOINTS)[0]
            return KindVerdict(
                KIND_INTERACTIVE,
                MARKER_INTERACTIVE_ENTRYPOINT,
                f"records carry entrypoint '{entry}', a human-driven path",
            )
        if HEADLESS_ENTRYPOINT in found.entrypoints:
            return KindVerdict(
                KIND_AUTOMATED,
                MARKER_HEADLESS_ENTRYPOINT,
                f"every record carries entrypoint '{HEADLESS_ENTRYPOINT}', "
                "the headless SDK path",
            )
    if found.plan_content:
        return KindVerdict(
            KIND_INTERACTIVE,
            MARKER_PLAN_APPROVED,
            "a user record carries planContent, so a human read a plan in "
            "the TUI and approved it",
        )
    if found.tui_record is not None:
        return KindVerdict(
            KIND_INTERACTIVE,
            MARKER_TUI_RECORD,
            f"the transcript holds a '{found.tui_record}' record, which "
            "only the interactive TUI writes",
        )
    return KindVerdict(
        KIND_UNKNOWN,
        MARKER_NONE,
        "no marker in this transcript answers the question; the row stays "
        "in the owner's lists",
    )


def read_records(path: str, limit: int = MAX_RECORDS_SCANNED) -> List[dict]:
    records: List[dict] = []
    with open(path, "r", errors="replace") as handle:
        for line in handle:
            if len(records) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                decoded = json.loads(line)
            except ValueError:
                continue
            if isinstance(decoded, dict):
                records.append(decoded)
    return records


def classify_transcript(path: str) -> KindVerdict:
    try:
        records = read_records(path)
    except OSError as exc:
        return KindVerdict(
            KIND_UNKNOWN,
            MARKER_UNREADABLE,
            f"the transcript could not be read ({exc.strerror or exc}); "
            "that is not evidence of automation",
        )
    return classify_records(records)
