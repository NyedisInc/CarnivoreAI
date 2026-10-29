
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CONFLICT_SUFFIX_RE = re.compile(r" \d+$")

STATUS_CLEAN = "clean"
STATUS_CONFLICTS = "conflicts_present"
STATUS_CANNOT_DETERMINE = "cannot_determine"

SIBLING_NONEMPTY = "canonical_nonempty"
SIBLING_EMPTY = "canonical_empty"
SIBLING_MISSING = "canonical_missing"
SIBLING_UNKNOWN = "canonical_unknown"


@dataclass
class ConflictPair:

    conflict_path: str
    canonical_path: str
    sibling_state: str
    file_count: int
    byte_count: int
    canonical_file_count: Optional[int]

    def to_record(self) -> Dict[str, object]:
        return {
            "conflict_path": self.conflict_path,
            "canonical_path": self.canonical_path,
            "sibling_state": self.sibling_state,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "canonical_file_count": self.canonical_file_count,
        }


@dataclass
class ConflictReport:

    root: str = ""
    status: str = STATUS_CLEAN
    reason: str = ""
    pairs: List[ConflictPair] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0
    sole_copy_pairs: int = 0
    unreadable_count: int = 0
    unreadable_sample: List[Dict[str, str]] = field(default_factory=list)

    def to_record(self) -> Dict[str, object]:
        return {
            "root": self.root,
            "status": self.status,
            "reason": self.reason,
            "conflict_directories": len(self.pairs),
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "sole_copy_pairs": self.sole_copy_pairs,
            "unreadable_count": self.unreadable_count,
            "unreadable_sample": list(self.unreadable_sample),
            "pairs": [pair.to_record() for pair in self.pairs],
        }


def _measure_tree(path: Path, report: ConflictReport) -> Optional[tuple]:
    files = 0
    total = 0
    failed = False

    def _onerror(exc: OSError) -> None:
        nonlocal failed
        failed = True
        report.unreadable_count += 1
        if len(report.unreadable_sample) < 20:
            report.unreadable_sample.append(
                {"path": str(getattr(exc, "filename", path)),
                 "reason": str(exc)}
            )

    for current, _dirs, names in os.walk(str(path), onerror=_onerror):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError as exc:
                _onerror(exc)
                continue
            files += 1
    if failed:
        return None
    return files, total


def scan_for_conflicts(root: Path) -> ConflictReport:
    report = ConflictReport(root=str(root))
    root = Path(root)
    if not root.is_dir():
        report.status = STATUS_CANNOT_DETERMINE
        report.reason = f"corpus root is not a directory: {root}"
        return report

    found: List[Path] = []
    walk_failed = False

    def _onerror(exc: OSError) -> None:
        nonlocal walk_failed
        walk_failed = True
        report.unreadable_count += 1
        if len(report.unreadable_sample) < 20:
            report.unreadable_sample.append(
                {"path": str(getattr(exc, "filename", root)),
                 "reason": str(exc)}
            )

    for current, dirs, _names in os.walk(str(root), onerror=_onerror):
        for name in sorted(dirs):
            if CONFLICT_SUFFIX_RE.search(name):
                found.append(Path(current) / name)

    for conflict in sorted(found):
        canonical = conflict.parent / CONFLICT_SUFFIX_RE.sub("", conflict.name)
        measured = _measure_tree(conflict, report)
        if measured is None:
            files, byts = 0, 0
        else:
            files, byts = measured
        if not canonical.is_dir():
            state = SIBLING_MISSING
            canonical_files: Optional[int] = None
        else:
            sib = _measure_tree(canonical, report)
            if sib is None:
                state = SIBLING_UNKNOWN
                canonical_files = None
            else:
                canonical_files = sib[0]
                state = SIBLING_EMPTY if sib[0] == 0 else SIBLING_NONEMPTY
        if state in (SIBLING_EMPTY, SIBLING_MISSING):
            report.sole_copy_pairs += 1
        report.pairs.append(
            ConflictPair(
                conflict_path=str(conflict),
                canonical_path=str(canonical),
                sibling_state=state,
                file_count=files,
                byte_count=byts,
                canonical_file_count=canonical_files,
            )
        )
        report.total_files += files
        report.total_bytes += byts

    if report.unreadable_count or walk_failed:
        report.status = STATUS_CANNOT_DETERMINE
        report.reason = (
            f"{report.unreadable_count} path(s) could not be read; the "
            "counts below are a floor, not a total"
        )
    elif report.pairs:
        report.status = STATUS_CONFLICTS
        report.reason = (
            f"{len(report.pairs)} forked director"
            f"{'y' if len(report.pairs) == 1 else 'ies'}; "
            f"{report.sole_copy_pairs} hold the only copy of their session"
        )
    else:
        report.status = STATUS_CLEAN
        report.reason = "no forked directories found"
    return report


def positive_control(root: Path) -> Dict[str, object]:
    should_match = ["abc 2", "abc 3", "abc 10", "workflows 2"]
    should_not = ["abc", "abc2", "abc 2x", "workflows", "abc-2"]
    hits = [n for n in should_match if CONFLICT_SUFFIX_RE.search(n)]
    misses = [n for n in should_not if CONFLICT_SUFFIX_RE.search(n)]
    return {
        "passed": len(hits) == len(should_match) and not misses,
        "root": str(root),
        "matched": hits,
        "false_positives": misses,
    }
