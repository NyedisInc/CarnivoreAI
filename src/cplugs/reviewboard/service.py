
from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.cplugs.reviewboard import layout, ports, scan, state as board_states
from src.cplugs.reviewboard.errors import BoardNotFound
from src.cplugs.sdk import task_folders
from src.cplugs.sdk.computer import local_computer
from src.cplugs.reviewboard.schema import Sidecar


def _row(row: scan.BoardRow) -> Dict[str, Any]:
    task = {"item_id": row.task_item_id, "computer": row.task_computer, "github_issue": row.github_issue} if row.task_item_id else None
    return {"slug": row.slug, "status": row.status, "title": row.title, "kind": row.kind, "task": task, "revisions": row.revisions,
            "latest": row.latest_file, "rounds": row.rounds, "last_round_at": row.last_round_at, "last_activity": row.last_activity,
            "state": row.state, "etag": row.etag, "scratch": row.scratch, "project": row.project}


def _finding(finding: scan.Finding) -> Dict[str, str]:
    return {"board": finding.board, "level": finding.level, "code": finding.code, "message": finding.message}


def boards(root: Path, task: Optional[int] = None) -> Dict[str, Any]:
    rows, findings = _scanned(root, task)
    return _answer([_row(r) for r in rows], findings)


def _scanned(root: Path, task: Optional[int]) -> Tuple[List[scan.BoardRow], List[Dict[str, str]]]:
    result = scan.scan(root)
    rows = [r for r in result.boards if task is None or r.task_item_id == task]
    rows.sort(key=lambda r: (r.last_activity or "", r.slug), reverse=True)
    findings = [_finding(f) for f in result.findings]
    if result.root_error and not result.holds_no_board:
        findings.insert(0, {"board": "", "level": "error", "code": "root", "message": result.root_error})
    return rows, findings


@functools.lru_cache(maxsize=1)
def _here() -> Optional[str]:
    return local_computer()


def _read(root: Path, task: Optional[int]) -> Tuple[List[scan.BoardRow], List[Dict[str, str]], Optional[str]]:
    rows, findings = _scanned(root, task)
    return rows, findings, _here() if any(r.task_computer for r in rows) else None


def _answer(rows: List[Dict[str, Any]], findings: List[Dict[str, str]]) -> Dict[str, Any]:
    return {"boards": rows, "problems": findings, "clean": not any(f["level"] == "error" for f in findings)}


MAX_PROJECT_KEY = 64
# could not be read
TASKS_UNREAD = {"board": "", "level": "warning", "code": "tasks_unread",
                "message": "the linked tasks could not be read, so no board shows as closed"}


def _local_task(row: scan.BoardRow, here: Optional[str]) -> bool:
    return row.task_item_id is not None and (not row.task_computer or not here or row.task_computer == here)


async def _tasks(rows: List[scan.BoardRow], here: Optional[str]) -> Tuple[Dict[int, Dict[str, Any]], bool]:
    ids = sorted({r.task_item_id for r in rows if _local_task(r, here)})
    port = ports.find()
    if not ids or port is None:
        return {}, True
    found = await port.items_info(ids)
    return (found, True) if found is not None else ({}, False)


def _task_project(info: Optional[Dict[str, Any]]) -> Optional[str]:
    key = str((info or {}).get("list") or "")
    return key if task_folders.is_project_key(key) else None


def _listed(row: scan.BoardRow, info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = _row(row)
    out["state"] = board_states.closed_over(row.state, info.get("state") if info else None)
    out["project"] = _task_project(info) or out["project"]
    if out["state"] == board_states.CLOSED:
        out["closed_at"] = row.last_revision_at
        out["task_title"] = info.get("title") if info else None
    return out


async def listing(root: Path, task: Optional[int] = None, state: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    rows, findings, here = await asyncio.to_thread(_read, root, task)
    tasks, read = await _tasks(rows, here)
    if not read:
        findings.append(dict(TASKS_UNREAD))
    listed = [_listed(r, tasks.get(r.task_item_id) if _local_task(r, here) else None) for r in rows]
    listed = [r for r in listed if (state is None or r["state"] == state) and (project is None or r["project"] == project)]
    if state == board_states.CLOSED:
        listed.sort(key=lambda r: (r["closed_at"] or "", r["slug"]), reverse=True)
    return _answer(listed, findings)


def sidecar_json(sidecar: Sidecar) -> Dict[str, Any]:
    return sidecar.model_dump(mode="json", by_alias=True)


def board(root: Path, slug: str) -> Dict[str, Any]:
    folder = layout.board_dir(root, slug)
    if folder is None:
        raise BoardNotFound(f"no board {slug} under the boards folder")
    found = scan.inspect_board(folder)
    sidecar: Any = sidecar_json(found.sidecar) if found.sidecar else (found.raw if found.row.status == "newer" else None)
    return {"slug": slug, "status": found.row.status, "state": found.row.state, "etag": found.row.etag, "sidecar": sidecar,
            "orphans": [f.message for f in found.findings if f.code == "orphan"], "findings": [_finding(f) for f in found.findings],
            "revision_dir": str(folder)}


def rounds_after(answer: Dict[str, Any], since_round: int) -> Dict[str, Any]:
    sidecar = answer.get("sidecar")
    if not isinstance(sidecar, dict) or not isinstance(sidecar.get("rounds"), list):
        return answer
    kept = [r for r in sidecar["rounds"] if isinstance(r, dict) and isinstance(r.get("n"), int) and r["n"] > since_round]
    return {**answer, "sidecar": {**sidecar, "rounds": kept}}


SAVES_MODES = ("all", "latest", "none")


def with_saves(answer: Dict[str, Any], mode: str) -> Dict[str, Any]:
    sidecar = answer.get("sidecar")
    if mode == "all" or not isinstance(sidecar, dict) or not isinstance(sidecar.get("revisions"), list):
        return answer

    def narrowed(rev: Any) -> Any:
        if not isinstance(rev, dict) or not rev.get("saves"):
            return rev
        kept = {k: v for k, v in rev.items() if k != "saves"}
        return {**kept, "saves": rev["saves"][-1:]} if mode == "latest" else kept

    return {**answer, "sidecar": {**sidecar, "revisions": [narrowed(r) for r in sidecar["revisions"]]}}
