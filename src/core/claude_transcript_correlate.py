
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()

PROBE_ENTRYPOINT = "sdk-cli"

DEFAULT_MAX_LINES_SCANNED = 50

CORRELATE_MATCHED = "matched"

CORRELATE_NO_CANDIDATE = "no_candidate"

CORRELATE_AMBIGUOUS = "ambiguous"

CORRELATE_ERROR = "error"

CORRELATE_NO_MATCH: Tuple[str, ...] = (
    CORRELATE_NO_CANDIDATE,
    CORRELATE_AMBIGUOUS,
    CORRELATE_ERROR,
)


@dataclass(frozen=True)
class CorrelationResult:

    outcome: str
    claude_session_uuid: Optional[str] = None
    transcript_path: Optional[str] = None
    detail: Optional[str] = None

    @property
    def matched(self) -> bool:
        return self.outcome == CORRELATE_MATCHED


@dataclass(frozen=True)
class _Candidate:

    path: Path
    claude_session_uuid: str
    start_epoch: float


def default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


_PROJECT_DIR_KEEP = re.compile(r"[^A-Za-z0-9-]")


def slugify_project_dir(working_dir: str) -> str:
    return _PROJECT_DIR_KEEP.sub("-", working_dir)


def _parse_timestamp(value: object) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _classify_transcript(
    path: Path, *, max_lines_scanned: int
) -> Optional[Tuple[float, str]]:
    try:
        with path.open("r", encoding="utf-8", errors="strict") as fh:
            for i, raw_line in enumerate(fh):
                if i >= max_lines_scanned:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") != "user" or record.get("isSidechain") is not False:
                    continue
                if record.get("entrypoint") == PROBE_ENTRYPOINT:
                    return None
                epoch = _parse_timestamp(record.get("timestamp"))
                if epoch is None or not record.get("sessionId"):
                    return None
                return (epoch, path.stem)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "claude_transcript_read_failed",
            path=str(path),
            error=str(exc),
        )
        return None
    return None


def correlate_adopted_session(
    *,
    working_dir: Optional[str],
    tmux_created_epoch: Optional[int],
    projects_dir: Optional[Path] = None,
    epoch_slack_seconds: int = 5,
    max_lines_scanned: int = DEFAULT_MAX_LINES_SCANNED,
) -> CorrelationResult:
    if not working_dir:
        return CorrelationResult(
            outcome=CORRELATE_NO_CANDIDATE,
            detail="no working directory to resolve a claude project from",
        )
    if tmux_created_epoch is None:
        return CorrelationResult(
            outcome=CORRELATE_NO_CANDIDATE,
            detail="tmux instance has no creation epoch to anchor a match against",
        )

    from src.core.claude_project_dirs import candidate_project_dirs

    project_dirs = candidate_project_dirs(
        working_dir,
        projects_dir=projects_dir,
        default_dir=default_projects_dir() if projects_dir is None else None,
    )

    entries: List[Path] = []
    listed: List[Path] = []
    for project_dir in project_dirs:
        try:
            if not project_dir.is_dir():
                continue
            entries.extend(sorted(
                p for p in project_dir.iterdir() if p.is_file() and p.suffix == ".jsonl"
            ))
            listed.append(project_dir)
        except OSError as exc:
            logger.warning(
                "claude_transcript_scan_failed",
                working_dir=working_dir,
                project_dir=str(project_dir),
                error=str(exc),
            )
            return CorrelationResult(
                outcome=CORRELATE_ERROR,
                detail=f"could not list the claude project directory: {exc}",
            )
    if not listed:
        return CorrelationResult(
            outcome=CORRELATE_NO_CANDIDATE,
            detail=f"no claude project directory for {working_dir}",
        )
    project_dir = listed[0]

    floor = tmux_created_epoch - epoch_slack_seconds
    candidates: List[_Candidate] = []
    for path in entries:
        info = _classify_transcript(path, max_lines_scanned=max_lines_scanned)
        if info is None:
            continue
        start_epoch, claude_session_uuid = info
        if start_epoch < floor:
            continue
        if any(c.claude_session_uuid == claude_session_uuid for c in candidates):
            continue
        candidates.append(
            _Candidate(
                path=path,
                claude_session_uuid=claude_session_uuid,
                start_epoch=start_epoch,
            )
        )

    if not candidates:
        return CorrelationResult(
            outcome=CORRELATE_NO_CANDIDATE,
            detail=(
                f"no transcript in {project_dir} starts at or after this "
                "tmux session's creation time"
            ),
        )

    if len(candidates) > 1:
        return CorrelationResult(
            outcome=CORRELATE_AMBIGUOUS,
            detail=(
                f"{len(candidates)} transcripts in {project_dir} could "
                "plausibly be this pane's conversation - refusing to guess"
            ),
        )

    only = candidates[0]
    return CorrelationResult(
        outcome=CORRELATE_MATCHED,
        claude_session_uuid=only.claude_session_uuid,
        transcript_path=str(only.path),
    )
