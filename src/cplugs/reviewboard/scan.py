"""THE SCANNER: rebuild every board from the boards folder alone (``docs/reviewboard.md``, "The scanner").

A pure function of the folder: no database, no network, no write, nothing deleted. The command-line scanner
(``cli/scan.py``), the repo test over ``design/boards/`` and (from slice 2) the server's ``GET /boards`` all call
:func:`scan`. It never follows a symlink.

WHAT IT CHECKS, per board folder: the folder name is a slug and equals ``board.slug``; ``sidecar.json`` parses and
validates (``document.parse_sidecar``); every revision view file exists as a regular file whose sha256 and byte count
match the sidecar (revision files are IMMUTABLE); nothing else lies in the folder. A sidecar of a NEWER schema version is
listed read only, unvalidated. A file or folder that exists but cannot be read (a permission, an iCloud placeholder) is
that board's ``unreadable`` error, never a crash that hides every other board.

WHERE IT LOOKS (``layout.py``, #1733). A board folder directly under the root (the flat shape, every board made before #1733) and
one under a task's ``boards/`` in the Task Manager layout (``<root>/<project>/<task>/boards/<slug>/``; project and task folders are
known by their markers, ``sdk/task_folders.py``). A project folder is walked, never reported as an unknown entry; anything else in a
task folder (``pastes/``, ``artifacts/``) is not the board's business. A slug found twice is an error on the second.

EXIT MEANING (gotcha 11: a green check must be able to go red). :attr:`ScanResult.exit_code` is 0 clean (warnings
allowed), 1 at least one error, 2 COULD NOT SCAN: the root is missing, not a folder, a symlink, has no ``.boards-root``
marker, or holds no board at all, so nothing was looked at and nothing may read as a pass.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.cplugs.reviewboard import document, layout, scratch_files, state
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES, Sidecar
from src.cplugs.sdk import task_folders

MARKER = task_folders.ROOT_MARKER
ROOT_FILES = frozenset({MARKER, "README.md"})
VIEW_WARN_BYTES = 512 * 1024
BOARD_WARN_BYTES = 20 * 1024 * 1024
MAX_SIDECAR_BYTES = 16 * 1024 * 1024
_EXT_FILE = re.compile(r"ext-[a-z][a-z0-9]{1,23}-[a-z0-9-]{1,48}\.json")
_SLUG = layout.SLUG


NO_BOARDS = "holds no board, so nothing was checked"


@dataclass(frozen=True)
class Finding:

    board: str
    level: str
    code: str
    message: str


@dataclass(frozen=True)
class BoardRow:
    """One board as the folder alone describes it. ``status``: ``ok``, ``invalid`` (listed, unusable) or ``newer``
    (made by a newer build: read only). The counts and names are None when the sidecar could not be read. ``project`` is the list
    key the board's project folder marker names (``<root>/<project>/<task>/boards/<slug>/``), None for a flat board or the
    ``no-project`` folder; ``last_revision_at`` is the newest revision's time (a closed board's ``closed_at``, ``service.listing``)."""

    slug: str
    status: str
    title: Optional[str] = None
    kind: Optional[str] = None
    task_item_id: Optional[int] = None
    task_computer: Optional[str] = None
    github_issue: Optional[str] = None
    revisions: Optional[int] = None
    latest_file: Optional[str] = None
    rounds: Optional[int] = None
    last_round_at: Optional[str] = None
    last_activity: Optional[str] = None
    state: Optional[str] = None
    etag: Optional[str] = None
    scratch: bool = False
    project: Optional[str] = None
    last_revision_at: Optional[str] = None


@dataclass(frozen=True)
class ScanResult:

    root: str
    boards: Tuple[BoardRow, ...] = ()
    findings: Tuple[Finding, ...] = ()
    root_error: Optional[str] = None

    @property
    def errors(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "error")

    @property
    def exit_code(self) -> int:
        """0 clean, 1 errors found, 2 could not scan. Output: int."""
        return 2 if self.root_error else (1 if self.errors else 0)

    @property
    def holds_no_board(self) -> bool:
        return bool(self.root_error) and self.root_error.endswith(NO_BOARDS)


@dataclass
class _Board:

    name: str
    findings: List[Finding] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append(Finding(self.name, level, code, message))


def _regular(path: Path) -> Optional[os.stat_result]:
    try:
        st = path.lstat()
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def _unreadable(board: _Board, name: str, exc: OSError) -> None:
    """Record a file or folder that exists but could not be read, naming the error number. Inputs: board; name; exc."""
    reason = errno.errorcode.get(exc.errno, "unknown") if exc.errno is not None else type(exc).__name__
    board.add("error", "unreadable", f"{name} could not be read ({reason})")


def _view_file(folder: Path, name: str, where: str, board: _Board) -> Optional[Tuple[str, int]]:
    st = _regular(folder / name)
    if st is None:
        board.add("error", "missing_file", f"{where}: {name} is missing, or is not a regular file")
        return None
    if st.st_size > MAX_VIEW_BYTES:
        board.add("error", "too_large", f"{name} is {st.st_size} bytes; a view is at most {MAX_VIEW_BYTES}")
        return None
    try:
        data = (folder / name).read_bytes()
    except OSError as exc:
        _unreadable(board, name, exc)
        return None
    if len(data) > VIEW_WARN_BYTES:
        board.add("warning", "large_view", f"{name} is {len(data)} bytes; past {VIEW_WARN_BYTES} it weighs on the repo")
    return hashlib.sha256(data).hexdigest(), len(data)


def _check_views(folder: Path, sidecar: Sidecar, board: _Board) -> Set[str]:
    files: Dict[str, Optional[Tuple[str, int]]] = {}
    for rev in sidecar.revisions:
        for view in rev.views:
            if view.file not in files:
                files[view.file] = _view_file(folder, view.file, f"{rev.id} view {view.id}", board)
            found = files[view.file]
            if found is not None and found != (view.sha256, view.bytes):
                board.add("error", "hash_mismatch", f"{rev.id} view {view.id}: {view.file} does not match its recorded sha256 and size "
                          "(revision files are immutable; a change is a new revision)")
    return set(files)


def _check_draft_files(folder: Path, sidecar: Sidecar, board: _Board) -> Set[str]:
    """The live draft's page files (#1725): each must be there as a regular file, but its hash is NOT compared, because the draft is overwritten in
    place and a scan can land between the page write and the sidecar write (the viewer re-reads once; a revision's file stays immutable).

    Inputs: folder; sidecar; board. Output: the file names the live slot names (empty for a board that is not live).
    """
    names: Set[str] = set()
    for view in sidecar.live.draft.views if sidecar.live else []:
        names.add(view.file)
        _view_file(folder, view.file, f"the live draft view {view.id}", board)
    return names


def _check_folder_files(folder: Path, named: Set[str], board: _Board, allowed: Set[str] = frozenset()) -> None:
    total = 0
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        _unreadable(board, "the board folder", exc)
        return
    for entry in entries:
        st = _regular(entry)
        total += st.st_size if st else 0
        if entry.name == document.SIDECAR_FILE or entry.name in named or entry.name in allowed or entry.name.startswith("."):
            continue
        if st is not None and _EXT_FILE.fullmatch(entry.name):
            continue
        what = "an orphan file (no revision names it)" if st is not None else "not a regular file"
        board.add("warning", "orphan", f"{entry.name} is {what}; the scanner never deletes anything")
    if total > BOARD_WARN_BYTES:
        board.add("warning", "large_board", f"the board holds {total} bytes; past {BOARD_WARN_BYTES} it weighs on the repo")


def _read_sidecar(folder: Path, board: _Board) -> Tuple[Optional[bytes], Optional[object]]:
    st = _regular(folder / document.SIDECAR_FILE)
    if st is None:
        board.add("error", "no_sidecar", f"{document.SIDECAR_FILE} is missing, or is not a regular file")
        return None, None
    if st.st_size > MAX_SIDECAR_BYTES:
        board.add("error", "too_large", f"{document.SIDECAR_FILE} is {st.st_size} bytes; the limit is {MAX_SIDECAR_BYTES}")
        return None, None
    try:
        data = (folder / document.SIDECAR_FILE).read_bytes()
    except OSError as exc:
        _unreadable(board, document.SIDECAR_FILE, exc)
        return None, None
    try:
        return data, json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        board.add("error", "unreadable", f"{document.SIDECAR_FILE} is not UTF-8 JSON ({type(exc).__name__})")
        return data, None


@dataclass(frozen=True)
class Inspected:

    row: BoardRow
    findings: List[Finding]
    sidecar: Optional[Sidecar] = None
    raw: Optional[object] = None
    data: Optional[bytes] = None


def project_of(folder: Path) -> Optional[str]:
    boards = folder.parent
    task = boards.parent
    if boards.name != task_folders.BOARDS or task_folders.task_item_of(task) is None or not task_folders.is_project_folder(task.parent):
        return None
    return task_folders.project_list_of(task.parent)


def inspect_board(folder: Path) -> Inspected:
    board = _Board(folder.name)
    project = project_of(folder)
    if not _SLUG.fullmatch(folder.name):
        board.add("error", "bad_folder", f"the folder name {folder.name} is not a board slug (YYYYMMDD-words)")
    data, raw = _read_sidecar(folder, board)
    if raw is None:
        return Inspected(BoardRow(slug=folder.name, status="invalid", etag=document.etag(data) if data else None, project=project), board.findings, data=data)
    tag = document.etag(data or b"")
    if document.is_newer(raw):
        board.add("warning", "newer", "made by a newer Carnivore: listed read only and never written")
        return Inspected(BoardRow(slug=folder.name, status="newer", etag=tag, project=project), board.findings, raw=raw, data=data)
    try:
        sidecar = document.parse_sidecar(raw)
    except document.SidecarInvalid as exc:
        for problem in exc.problems:
            board.add("error", "invalid", problem)
        return Inspected(BoardRow(slug=folder.name, status="invalid", etag=tag, project=project), board.findings, raw=raw, data=data)
    if sidecar.board.slug != folder.name:
        board.add("error", "slug_mismatch", f"board.slug {sidecar.board.slug} differs from its folder name")
    if document.canonical_text(sidecar).encode("utf-8") != data:
        board.add("warning", "not_canonical", "the sidecar is valid but not in canonical form (hand edited?); the writer rewrites it")
    named = _check_views(folder, sidecar, board) | _check_draft_files(folder, sidecar, board)
    _check_folder_files(folder, named, board, scratch_files.check_folder(folder, sidecar, board.add))
    last = sidecar.revisions[-1] if sidecar.revisions else None
    task = sidecar.task
    errors = any(f.level == "error" for f in board.findings)
    row = BoardRow(slug=folder.name, status="invalid" if errors else "ok", title=sidecar.board.title, kind=sidecar.board.kind,
                   task_item_id=task.item_id if task else None, task_computer=task.computer if task else None,
                   github_issue=task.github_issue if task else None, revisions=len(sidecar.revisions),
                   latest_file=last.views[0].file if last else None, rounds=len(sidecar.rounds),
                   last_round_at=sidecar.rounds[-1].sent_at if sidecar.rounds else None,
                   last_activity=state.last_activity(sidecar), state=state.board_state(sidecar), etag=tag,
                   scratch=scratch_files.is_scratch(sidecar), project=project,
                   last_revision_at=last.created_at if last else None)
    return Inspected(row, board.findings, sidecar=sidecar, raw=raw, data=data)


def scan_board(folder: Path) -> Tuple[BoardRow, List[Finding]]:
    found = inspect_board(folder)
    return found.row, found.findings


def _root_problem(root: Path) -> Optional[str]:
    try:
        st = root.lstat()
    except OSError:
        return f"{root} does not exist"
    if stat.S_ISLNK(st.st_mode):
        return f"{root} is a symlink; name the real folder"
    if not stat.S_ISDIR(st.st_mode):
        return f"{root} is not a folder"
    if _regular(root / MARKER) is None:
        return f"{root} is not a boards folder (no {MARKER} marker file)"
    return None


def scan(root: Path) -> ScanResult:
    problem = _root_problem(root)
    if problem:
        return ScanResult(root=str(root), root_error=problem)
    rows: List[BoardRow] = []
    findings: List[Finding] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        return ScanResult(root=str(root), root_error=f"{root} could not be listed ({exc.strerror or type(exc).__name__})")
    flat = [e for e in entries if not e.name.startswith(".") and e.name not in ROOT_FILES and not layout.is_container(e)]
    seen: Set[str] = set()
    for entry in [*flat, *layout.nested_entries(root)]:
        where = entry.relative_to(root).as_posix()
        if entry.is_symlink() or not entry.is_dir():
            findings.append(Finding("", "warning", "unknown_entry", f"{where} is not a board folder; the scanner never deletes anything"))
            continue
        if entry.name in seen:
            findings.append(Finding(entry.name, "error", "duplicate_slug", f"{where} repeats a board name already in the folder; a name is one board"))
            continue
        seen.add(entry.name)
        row, found = scan_board(entry)
        rows.append(row)
        findings.extend(found)
    if not rows:
        return ScanResult(root=str(root), findings=tuple(findings), root_error=f"{root} {NO_BOARDS}")
    return ScanResult(root=str(root), boards=tuple(sorted(rows, key=lambda r: r.slug)), findings=tuple(findings))
