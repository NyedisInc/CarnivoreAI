
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from scripts.backup.db_snapshot import describe_database, diff_tables, file_sha256
from scripts.backup.errors import PhaseBackupError, SetUnreadable
from scripts.backup.file_snapshot import describe_file, describe_tree, diff_files
from scripts.backup.targets import MANIFEST_FORMAT, MANIFEST_NAME


@dataclass
class Report:

    failures: List[str] = field(default_factory=list)
    allowed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def load_manifest(set_dir: Path) -> Dict[str, Any]:
    try:
        manifest = json.loads((set_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetUnreadable(f"{set_dir}: no readable {MANIFEST_NAME} ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT or not {"databases", "files", "trees"} <= set(manifest):
        raise SetUnreadable(f"{set_dir}: {MANIFEST_NAME} is not format {MANIFEST_FORMAT}")
    return manifest


def _record(report: Report, key: str, message: str, allow: Sequence[str]) -> None:
    line = f"{key}: {message}"
    (report.allowed if any(fnmatch.fnmatch(key, pat) for pat in allow) else report.failures).append(line)


def check_set(set_dir: Path, manifest: Dict[str, Any], report: Report) -> None:
    for name, entry in manifest["databases"].items():
        path = set_dir / entry["copy"]
        if not path.is_file():
            report.failures.append(f"set {name}: the copy {entry['copy']} is missing")
            continue
        try:
            now = describe_database(path, check_integrity=True)
        except PhaseBackupError as exc:
            report.failures.append(f"set {name}: {exc}")
            continue
        if now["integrity"] != "ok":
            report.failures.append(f"set {name}: integrity check says {now['integrity'][:80]}")
        report.failures.extend(f"set {name}:{p}" for p in diff_tables(entry["tables"], now["tables"]))
        if file_sha256(path) != entry["file_sha256"]:
            report.failures.append(f"set {name}: the file's sha256 differs from the manifest")
    for key, entry in manifest["files"].items():
        path = set_dir / entry["copy"]
        if not path.is_file() or file_sha256(path) != entry["sha256"]:
            report.failures.append(f"set file {key}: missing or changed")
    for tree, entry in manifest["trees"].items():
        removed, changed, added = diff_files(entry["files"], describe_tree(set_dir / "files" / tree))
        report.failures.extend(f"set file {tree}/{p}: {what}" for what, paths in (("missing", removed), ("changed", changed), ("unexpected", added)) for p in paths)


def check_live(manifest: Dict[str, Any], state_dir: Path, report: Report, allow: Sequence[str],
               resolver: Any) -> None:
    for name, entry in manifest["databases"].items():
        live = resolver(state_dir, name)
        if live is None:
            _record(report, f"{name}", "the live database is gone", allow)
            continue
        now = describe_database(live, check_integrity=False)
        for sentence in diff_tables(entry["tables"], now["tables"]):
            table = sentence.split(":", 1)[0]
            _record(report, f"{name}:{table}", sentence.split(": ", 1)[1], allow)
    for key, entry in manifest["files"].items():
        live = Path(entry["source"]) if entry["base"] == "abs" else state_dir / key
        if not live.is_file():
            _record(report, f"file:{key}", "the live file is gone", allow)
        elif describe_file(live)["sha256"] != entry["sha256"]:
            _record(report, f"file:{key}", "content changed", allow)
    for tree, entry in manifest["trees"].items():
        removed, changed, added = diff_files(entry["files"], describe_tree(state_dir / tree))
        for what, paths in (("deleted", removed), ("changed", changed)):
            for path in paths:
                _record(report, f"file:{tree}/{path}", what, allow)
        report.notes.extend(f"new file {tree}/{p}" for p in added)


def verify_set(set_dir: Path, state_dir: Optional[Path], allow: Sequence[str], resolver: Any) -> Report:
    """Verify a set, and the live data against it when ``state_dir`` is given.

    Inputs: set_dir (Path); state_dir (Path | None - None checks the set alone); allow (patterns); resolver (see check_live).
    Output: Report. Raises: SetUnreadable (no manifest), PhaseBackupError (a live database could not be read).
    """
    manifest = load_manifest(set_dir)
    report = Report()
    check_set(set_dir, manifest, report)
    if state_dir is not None:
        check_live(manifest, state_dir, report, allow, resolver)
    return report
