
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from src.core.dev_tools import git_guard
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from src.core.message_model_secrets import (
    VENDOR_DETECTORS,
    SecretFinding,
    scan_text,
)

FILE_DETECTORS: Tuple[str, ...] = VENDOR_DETECTORS

MAX_FILE_BYTES: int = 1_000_000

SKIP_DIRS: Tuple[str, ...] = (
    ".git", "venv", ".venv", "node_modules", "__pycache__", ".worktrees",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".tox",
)

SKIP_SUFFIXES: Tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip",
    ".gz", ".tgz", ".bz2", ".xz", ".woff", ".woff2", ".ttf", ".otf",
    ".eot", ".mp3", ".mp4", ".m4a", ".ogg", ".wav", ".so", ".dylib",
    ".pyc", ".class", ".jar", ".db", ".sqlite", ".sqlite3",
)

SKIP_PATH_PARTS: Tuple[str, ...] = ("client/vendor/", "scripts/codemirror-vendor/")

PRAGMA_RE = re.compile(r"secret-scan:\s*allow\s+\S")

EXCERPT_CONTEXT_CHARS: int = 32

MASK: str = "***"


@dataclass(frozen=True)
class FileFinding:

    path: str
    line: int
    column: int
    detector: str
    length: int
    value_sha256: str
    excerpt: Optional[str]

    def render(self) -> str:
        head = (
            f"{self.path}:{self.line}:{self.column} {self.detector} "
            f"({self.length} chars, sha256 {self.value_sha256[:12]})"
        )
        return f"{head}\n    {self.excerpt}" if self.excerpt else head


def _line_starts(text: str) -> List[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _locate(starts: Sequence[int], offset: int) -> Tuple[int, int]:
    low, high = 0, len(starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low + 1, offset - starts[low] + 1


def _excerpt_for(
    text: str, starts: Sequence[int], target: SecretFinding,
    all_findings: Iterable[SecretFinding],
) -> str:
    """Build a masked, truncated excerpt of the line holding a match.

    Description: EVERY finding that overlaps the line is masked, not only
      the target, so a line carrying two credentials cannot print one of
      them while reporting the other. The window is then cut to
      EXCERPT_CONTEXT_CHARS either side of the mask, which bounds how
      much unexamined neighbouring text is shown.
    Inputs: text (str - the whole file), starts (from _line_starts),
      target (SecretFinding being rendered), all_findings (every finding
      in this file).
    Output: str - safe to print.
    Example: masked output looks like 'token = "***"'
    """
    line_index = _locate(starts, target.offset)[0] - 1
    begin = starts[line_index]
    end = starts[line_index + 1] - 1 if line_index + 1 < len(starts) else len(text)

    spans = sorted(
        (f.offset, f.offset + f.length)
        for f in all_findings
        if f.offset < end and f.offset + f.length > begin
    )
    pieces: List[str] = []
    cursor = begin
    mask_at = 0
    for span_start, span_end in spans:
        span_start, span_end = max(span_start, begin), min(span_end, end)
        pieces.append(text[cursor:span_start])
        if span_start <= target.offset:
            mask_at = sum(len(p) for p in pieces)
        pieces.append(MASK)
        cursor = span_end
    pieces.append(text[cursor:end])
    masked = "".join(pieces)

    low = max(0, mask_at - EXCERPT_CONTEXT_CHARS)
    high = min(len(masked), mask_at + len(MASK) + EXCERPT_CONTEXT_CHARS)
    window = masked[low:high].strip()
    prefix = "..." if low > 0 else ""
    suffix = "..." if high < len(masked) else ""
    return f"{prefix}{window}{suffix}"


def line_text(text: str, starts: Sequence[int], line: int) -> str:
    begin = starts[line - 1]
    end = starts[line] - 1 if line < len(starts) else len(text)
    return text[begin:end]


def scan_content(
    path: str, text: str, detectors: Optional[Iterable[str]] = None,
    excerpts: bool = True, honour_pragma: bool = True,
) -> Tuple[List[FileFinding], int]:
    chosen = FILE_DETECTORS if detectors is None else detectors
    raw = scan_text(text, detectors=chosen)
    if not raw:
        return [], 0
    starts = _line_starts(text)
    out: List[FileFinding] = []
    suppressed = 0
    for finding in raw:
        line, column = _locate(starts, finding.offset)
        if honour_pragma and PRAGMA_RE.search(line_text(text, starts, line)):
            suppressed += 1
            continue
        out.append(
            FileFinding(
                path=path,
                line=line,
                column=column,
                detector=finding.detector,
                length=finding.length,
                value_sha256=finding.value_sha256,
                excerpt=(
                    _excerpt_for(text, starts, finding, raw)
                    if excerpts else None
                ),
            )
        )
    return out, suppressed


def should_skip(path: Path) -> bool:
    posix = path.as_posix()
    if any(part in posix for part in SKIP_PATH_PARTS):
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    try:
        return path.stat().st_size > MAX_FILE_BYTES
    except OSError:
        return False


def read_text_or_none(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def iter_candidate_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    tracked = _git_tracked_files(root)
    if tracked is not None:
        yield from tracked
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _git_tracked_files(root: Path) -> Optional[List[Path]]:
    """Files git tracks under a root, or None when it is not a work tree.

    Inputs: root (Path).
    Output: list[Path] or None. None is "git could not answer", which the
      caller turns into a filesystem walk rather than into an empty list.
    Example: _git_tracked_files(Path("/tmp")) -> None
    """
    if not git_guard.git_available():
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    names = done.stdout.decode("utf-8", "replace").split("\0")
    return [root / name for name in names if name]
