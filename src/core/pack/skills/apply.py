
from __future__ import annotations

import errno
import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import structlog

from src.core.pack.skills import alerts, receiver, rules
from src.core.pack.skills.bundle import Bundle
from src.core.pack.skills.receiver import ReceiverState
from src.core.pack.skills.scan import scan_skill
from src.core.pack.skills.targets import REASON_ROOT_LINK, SkillRoot, roots_for
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS, PACK_SKILLS
from src.core.skill_manager.root_create import RootCreateRefused, create_leaf_root
from src.core.skills.digest import MODE_EXECUTABLE
from src.core.skills.records import SIDECAR_NAME
from src.core.skills.targets import copy_tree, move_to_trash, remove_tree
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

STAGE_DIR_NAME = ".carnivore-sync-stage"
REASON_NO_DISK = "no disk"
REASON_NOT_DELIVERED = "not delivered"


@dataclass
class ApplyReport:

    rows: list[dict[str, Any]] = field(default_factory=list)
    changed: bool = False
    kept: list[str] = field(default_factory=list)
    kept_items: list[tuple[str, str, str]] = field(default_factory=list)


def _row(cell: receiver.Cell, alpha: str, gen: int, digest: str, state: str, reason: str = "") -> dict[str, Any]:
    return {"family": cell.family, "name": cell.name, "root": str(cell.root.leaf), "alpha": alpha, "gen": gen,
            "digest": digest, "state": state, "reason": reason, "at": int(time.time()), "placed": False}


def _remember(data: dict[str, Any], family: str, name: str, digest: str) -> None:
    seen = data["seen"].setdefault(f"{family}/{name}", [])
    if digest not in seen:
        seen.append(digest)
        del seen[:-receiver.SEEN_PER_SKILL]


def _was_placed(data: dict[str, Any], alpha: str, row: dict[str, Any]) -> bool:
    return any(r.get("placed") is True and r.get("alpha") == alpha and all(r.get(k) == row[k] for k in ("family", "name", "root"))
               for r in data["applied"])


def _restore_machine_local(displaced: Path, target: Path) -> Optional[str]:
    problem = None
    for name in sorted(rules.MACHINE_LOCAL_NAMES):
        source, destination = displaced / name, target / name
        if os.path.lexists(source) and not os.path.lexists(destination):
            assert_test_write_allowed(destination)
            try:
                os.replace(source, destination)
            except OSError as exc:
                logger.warning("pack_skills_machine_local_move_failed", name=name, errno=exc.errno)
                problem = "machine-local folder left in trash"
    return problem


def _dispose(displaced: Path, name: str, family: str, data: dict[str, Any], trash: Path) -> bool:
    try:
        mine = scan_skill(displaced, name)
    except OSError:
        return True
    if mine.problem is not None:
        return True
    if mine.digest in data["seen"].get(f"{family}/{name}", []):
        remove_tree(displaced)
        return False
    try:
        siblings = [e for e in trash.iterdir() if e.name.startswith(name + "-") and e != displaced and e.is_dir() and not e.is_symlink()]
        for old in siblings:
            if scan_skill(old, name).digest == mine.digest:
                remove_tree(displaced)
                return False
    except OSError:
        pass
    return True


def _tidy_stage(stage_dir: Path, older_than: float = 86400.0) -> None:
    try:
        for leftover in stage_dir.iterdir():
            if not leftover.is_symlink() and time.time() - leftover.stat().st_mtime > older_than:
                remove_tree(leftover)
        stage_dir.rmdir()
    except OSError:
        pass


def _install(root: SkillRoot, family: str, name: str, source: Path, exec_paths: frozenset[str], need_bytes: int,
             stamp: str, data: dict[str, Any], report: ApplyReport) -> Optional[str]:
    leaf, target = root.leaf, root.leaf / name
    if target.is_symlink():
        return receiver.REASON_SKILL_LINK
    try:
        if not os.path.lexists(leaf):
            create_leaf_root(leaf, root.boundary)
            report.changed = True
        if shutil.disk_usage(leaf.parent).free < 2 * need_bytes:
            return REASON_NO_DISK
        stage_dir = leaf.parent / STAGE_DIR_NAME
        if os.path.lexists(stage_dir) and stage_dir.is_symlink():
            return REASON_ROOT_LINK
        assert_test_write_allowed(stage_dir)
        stage_dir.mkdir(mode=0o700, exist_ok=True)
        fresh = stage_dir / f"{name}-{secrets.token_hex(4)}"
        copy_tree(source, fresh, exec_paths=exec_paths)
    except RootCreateRefused:
        return REASON_ROOT_LINK
    except OSError as exc:
        logger.warning("pack_skills_stage_failed", family=family, errno=exc.errno)
        return REASON_NO_DISK if exc.errno in (errno.ENOSPC, errno.EXDEV, errno.EDQUOT) else "cannot write"
    try:
        if not os.path.lexists(target):
            assert_test_write_allowed(target)
            os.replace(fresh, target)
        else:
            displaced = move_to_trash(target, root.trash, f"{root.group}-{stamp}")
            if displaced.is_symlink():
                os.replace(displaced, target)
                remove_tree(fresh)
                return receiver.REASON_SKILL_LINK
            try:
                assert_test_write_allowed(target)
                os.replace(fresh, target)
            except OSError:
                os.replace(displaced, target)
                raise
            _restore_machine_local(displaced, target)
            if _dispose(displaced, name, family, data, root.trash):
                report.kept.append(str(displaced))
                report.kept_items.append((family, name, str(displaced)))
        report.changed = True
    except OSError as exc:
        logger.warning("pack_skills_swap_failed", family=family, errno=exc.errno)
        remove_tree(fresh)
        return REASON_NO_DISK if exc.errno in (errno.EXDEV, errno.ENOSPC) else "cannot write"
    _tidy_stage(stage_dir)
    return None


def _remove_placed_warez(family: str, name: str, root: SkillRoot, target: Any, stamp: str, report: ApplyReport,
                         data: dict[str, Any], services: Any) -> None:
    from src.core.pack.skills import placed_warez

    row = next((r for r in data["applied"] if r.get("item") and r.get("placed") is True
                and (r.get("family"), r.get("name"), r.get("root")) == (family, name, str(root.leaf))), None)
    verdict = placed_warez.KEPT
    if row is not None:
        verdict = (placed_warez.remove_mirror(row, root, target, f"{root.group}-{stamp}") if row.get("kind") == "mirror"
                   else placed_warez.remove_install(row, services))
    if verdict == placed_warez.REMOVED:
        report.changed = True
    elif verdict == placed_warez.KEPT:
        report.rows.append({"family": family, "name": name, "root": str(root.leaf), "alpha": "", "gen": 0, "digest": "",
                            "state": receiver.CONFLICT, "reason": "your own copy, kept", "at": int(time.time()), "placed": False})


def _remove_everywhere(removals: Sequence[Sequence[Any]], roots: Sequence[SkillRoot], stamp: str, report: ApplyReport,
                       data: dict[str, Any], services: Any = None) -> None:
    done = data.setdefault("removed", [])
    for family, name, *rest in removals:
        mark = [family, name, rest[0] if rest else 0]
        if mark in done:
            continue
        for root in roots_for(roots, family):
            target = root.leaf / name
            if root.problem or not os.path.lexists(target) or target.is_symlink():
                continue
            if os.path.lexists(target / SIDECAR_NAME):
                _remove_placed_warez(family, name, root, target, stamp, report, data, services)
                continue
            try:
                mine = scan_skill(target, name)
                if mine.problem is not None or mine.digest not in data["seen"].get(f"{family}/{name}", []):
                    report.rows.append({"family": family, "name": name, "root": str(root.leaf), "alpha": "", "gen": 0, "digest": "",
                                        "state": receiver.CONFLICT, "reason": "your own copy, kept", "at": int(time.time()),
                                        "placed": False})
                    continue
                move_to_trash(target, root.trash, f"{root.group}-{stamp}")
                report.changed = True
            except OSError as exc:
                logger.warning("pack_skills_remove_failed", family=family, errno=exc.errno)
        done.append(mark)
        del done[:-rules.MAX_SKILLS * 2]


def apply_document(doc: dict[str, Any], bundle: Optional[Bundle], roots: Sequence[SkillRoot], state: ReceiverState,
                   stamp: Optional[str] = None, services: Any = None) -> ApplyReport:
    stamp = stamp or f"{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}"
    report = ApplyReport()
    with state.lock:
        data = state.load()
        alpha, gen = doc["alpha"], doc["gen"]
        _remove_everywhere(doc["removals"], roots, stamp, report, data, services)
        for family, name, digest in doc["skills"]:
            staged = bundle.skills.get((family, name)) if bundle is not None else None
            for root in roots_for(roots, family):
                cell = receiver.classify(root, family, name, digest)
                reason, placed = cell.reason, False
                if cell.state in (receiver.MISSING, receiver.DIFFERS):
                    source = bundle.staging / family / name if (bundle is not None and staged is not None) else None
                    if source is None or not _verified(staged, digest):
                        reason, cell = REASON_NOT_DELIVERED, receiver.Cell(family, name, root, receiver.CONFLICT, REASON_NOT_DELIVERED)
                    else:
                        exec_paths = frozenset(e.path for e in staged if e.mode == MODE_EXECUTABLE)
                        problem = _install(root, family, name, source, exec_paths, sum(e.size for e in staged), stamp, data, report)
                        cell = receiver.Cell(family, name, root, receiver.IN_SYNC if problem is None else receiver.CONFLICT, problem or "")
                        reason = problem or ""
                        placed = problem is None
                if cell.state == receiver.IN_SYNC:
                    _remember(data, family, name, digest)
                row = _row(cell, alpha, gen, digest, cell.state, reason)
                row["placed"] = placed or (cell.state == receiver.IN_SYNC and _was_placed(data, alpha, row))
                report.rows.append(row)
        synced = {(f, n) for f, n, _ in doc["skills"]}
        gone = {(r[0], r[1]) for r in doc["unsynced"]} | {(r[0], r[1]) for r in doc["removals"]}
        refs = {(e[0], e[1]) for e in doc.get("warez", [])}
        data["applied"] = [r for r in data["applied"] if (r.get("family"), r.get("name")) not in synced | gone
                           and not (r.get("item") and r.get("placed") is not True and (r.get("family"), r.get("name")) not in refs)
                           ] + report.rows
        data["doc"], data["applied_gen"] = doc, gen
        state.save(data)
    notifier.notify(PACK_SKILLS)
    if report.changed:
        notifier.notify(LOCAL_SKILLS)
    for path in report.kept:
        logger.warning("pack_skills_local_edit_replaced", kept_in=os.path.dirname(path))
    alerts.replaced(report.kept_items, alpha, gen)
    return report


def place_skill(roots: Sequence[SkillRoot], family: str, name: str, bundle: Bundle, digest: str, stamp: Optional[str] = None) -> list[tuple[str, Optional[str]]]:
    stamp = stamp or f"{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}"
    staged = bundle.skills[(family, name)]
    exec_paths = frozenset(e.path for e in staged if e.mode == MODE_EXECUTABLE)
    report, data, out = ApplyReport(), {"seen": {}}, []
    for root in roots_for(roots, family):
        cell = receiver.classify(root, family, name, digest)
        problem = cell.reason if cell.state == receiver.CONFLICT else None
        if cell.state in (receiver.MISSING, receiver.DIFFERS):
            problem = _install(root, family, name, bundle.staging / family / name, exec_paths, sum(e.size for e in staged), stamp, data, report)
        out.append((root.group, problem))
    if report.changed:
        notifier.notify(LOCAL_SKILLS)
    return out


def _verified(entries: Sequence[Any], digest: str) -> bool:
    from src.core.skills.digest import DigestEntry, digest_entries

    return digest_entries(DigestEntry(e.path, e.mode, e.sha256) for e in entries) == digest


class ApplyWorker:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiting: Optional[tuple[str, Callable[[], None]]] = None
        self._thread: Optional[threading.Thread] = None

    def submit(self, job: Callable[[], None], on_replaced: Callable[[], None] = lambda: None) -> str:
        op_id = secrets.token_hex(6)
        with self._lock:
            replaced = self._waiting
            self._waiting = (op_id, job)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="pack-skills-apply", daemon=True)
                self._thread.start()
        if replaced is not None:
            on_replaced()
        return op_id

    def _run(self) -> None:
        while True:
            with self._lock:
                item, self._waiting = self._waiting, None
            if item is None:
                return
            try:
                item[1]()
            except Exception:  # noqa: BLE001
                logger.exception("pack_skills_apply_job_failed")

    def join(self, timeout: float = 30.0) -> bool:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not (thread is not None and thread.is_alive())
