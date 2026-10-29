"""Correlate an ADOPTED tmux session to the Claude conversation inside it.

THE GAP THIS CLOSES. ``sessions.claude_session_uuid`` has exactly one
writer today - ``session_lineage.record_claude_session`` - and it is
reached only from Claude Code's SessionStart hook, which fires only when
the app injected ``CLOUDECODE_SESSION_ID`` at spawn. A tmux session the
app ADOPTS instead of creates never gets that env var, so its
``claude_session_uuid`` stays NULL forever and every feature keyed on it
(fork resolution, resume, the out-of-band rename push) is dead for that
row. This module is the second writer, reached from the adopt path
(``session_adopt_persist.persist_adoption``), and it works from evidence
on disk instead of a live hook payload.

NEVER GUESS. The candidate set is every top-level transcript in that
project directory whose first real user message could plausibly have
been typed into THIS tmux pane - which means its timestamp is not
earlier than the pane's own creation time (an ``epoch_slack_seconds``
tolerance absorbs the few seconds between a pane existing and Claude's
first hook write actually landing). Exactly one such candidate is a
DECISIVE match. Zero is `no candidate ever started here`. More than one
is `more than one plausibly did`, and both of those are the SAME answer:
CANNOT DETERMINE. A tie is never broken by recency, size, or any other
heuristic - see :data:`CORRELATE_AMBIGUOUS`'s docstring for why breaking
it would be exactly the wrong kind of confident.

WHAT NEVER ENTERS THE CANDIDATE SET.

  A subagent transcript        excluded by path (see above), never read.
  An automated liveness probe  Claude Code's own healthcheck harness
                                writes a real top-level transcript with
                                ``entrypoint: "sdk-cli"`` on its first
                                user record. Measured against the corpus:
                                every "sdk-cli" transcript found was one
                                of these probes, and no genuine
                                interactive session anywhere in it
                                carried that entrypoint. Excluded outright
                                - a probe transcript is never a match
                                regardless of timing.
  An unclassifiable file       unreadable, not valid JSON on any of the
                                first ``max_lines_scanned`` lines, or
                                never reaching a top-level user record in
                                that window. Requirement: `if you cannot
                                classify a candidate, it is not a match`.
                                Excluding an unknown is the safe
                                direction here - the cost of a wrong
                                attach is high, the cost of a miss is the
                                NULL this module exists to sometimes fill.

FAIL SOFT. Every filesystem operation in :func:`correlate_adopted_session`
is wrapped so a permissions error, a missing directory, or a garbled file
degrades to ``CORRELATE_ERROR`` / ``CORRELATE_NO_CANDIDATE`` and never
raises into the adopt path. Reading the filesystem must never break an
adopt.

WHAT THIS MODULE DOES NOT DO. It does not write to the database - see
:func:`bind_correlated_uuid` for that half, which owns the unique-index
and archived-row safety properties separately so this module can stay a
pure, easily-fixtured reader.
"""

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

# COULD NOT EVALUATE
CORRELATE_NO_CANDIDATE = "no_candidate"

# COULD NOT EVALUATE
CORRELATE_AMBIGUOUS = "ambiguous"

# COULD NOT EVALUATE
# not usable
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

    if projects_dir is not None:
        bases: Tuple[Path, ...] = (projects_dir,)
    else:
        from src.core.claude_config.profile_roots import PROJECTS_DIRNAME, profile_subdir_roots

        bases = profile_subdir_roots(default_projects_dir(), PROJECTS_DIRNAME)
    slug = slugify_project_dir(working_dir)
    project_dirs = [base / slug for base in bases]

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
            detail=f"no claude project directory at {project_dirs[0]}",
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
