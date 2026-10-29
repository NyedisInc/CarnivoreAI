
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.core.inventory import claude_folders
from src.core.inventory.model import REPORT, Inventory
from src.core.inventory.resolve import resolve_project, resolve_session
from src.cplugs.save.vault.units import Scanner, Sources
from tests.python.inventory.world_build import build_world
from tests.python.inventory.world import CONV_A, CONV_A0, UUID_A

LINE = '{"type":"user"}\n'


def _write(path: Path, text: str = LINE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> SimpleNamespace:
    w = build_world(tmp_path_factory.mktemp("parity"))
    projects = w.home / "projects"
    enc1 = slugify_project_dir(w.root1)
    w.cases = {
        "set_aside": _write(projects / enc1 / f"{CONV_A}.jsonl.from-old-key-1"),
        "nested_2": _write(projects / "_hold-for-archive" / enc1 / f"{CONV_A0}.jsonl"),
        "nested_2_folder": _write(projects / "_hold-for-archive" / enc1 / CONV_A0 / "tool-results" / "t.txt", "x"),
        "nested_3": _write(projects / "_box" / "_inner" / enc1 / f"{CONV_A}.jsonl"),
        "notes": _write(projects / enc1 / "sessions-index.json", "{}"),
        "merged_side": _write(projects / enc1 / "_from--Users-x-old" / "memory" / "MEMORY.md", "# old\n"),
        "nested_notes": _write(projects / "_hold-for-archive" / enc1 / "memory" / "MEMORY.md", "# held\n"),
        "conflict": _write(projects / enc1 / f"{CONV_A} 2.jsonl"),
    }
    w.sources = Sources(claude_roots=(projects,), codex_home=w.codex, state_dir=w.state)
    w.enc1 = enc1
    return w


def _inventories(w: SimpleNamespace):
    with closing(connect(db_path_for(w.state))) as conn:
        return resolve_session(conn, UUID_A, w.locations), resolve_project(conn, w.p1, w.locations)


def _uncovered(planned: Iterable[Path], inventory: Inventory) -> List[str]:
    roots = [a.what for a in inventory.all_artifacts() if a.kind in ("file", "dir")]
    out = []
    for path in planned:
        text = str(path)
        if not any(text == r or text.startswith(r.rstrip(os.sep) + os.sep) for r in roots):
            out.append(text)
    return sorted(out)


def _vault_paths(w: SimpleNamespace) -> List[Path]:
    scan = Scanner(w.sources)
    paths = [f.path for conv in (CONV_A, CONV_A0) for f in (scan.plan_claude(conv).files)]
    for plan in scan.scan_memory().values():
        if plan.encoded_folder.split("/")[-1] == w.enc1:
            paths += [f.path for f in plan.files]
    return paths


def test_every_vault_planned_file_is_an_inventory_artifact(world: SimpleNamespace) -> None:
    session, project = _inventories(world)
    planned = _vault_paths(world)
    for case in ("set_aside", "nested_2", "nested_2_folder", "nested_3", "notes", "merged_side", "nested_notes"):
        assert world.cases[case] in planned, case
    assert _uncovered(planned, project) == []
    assert _uncovered([p for p in planned if "memory" not in p.parts and p.name != "sessions-index.json"], session) == []


def test_conflict_copies_are_traced_though_the_vault_skips_them(world: SimpleNamespace) -> None:
    session, _ = _inventories(world)
    assert _uncovered([world.cases["conflict"]], session) == []


def test_new_artifacts_are_report_so_a_purge_does_not_change(world: SimpleNamespace) -> None:
    session, _ = _inventories(world)
    extra = {str(world.cases[c]) for c in ("set_aside", "nested_3", "conflict")}
    extra.add(str(world.cases["nested_2"]))
    found = [a for a in session.artifacts if a.what in extra]
    assert len(found) == len(extra) and all(a.action == REPORT for a in found)
    top = [a for a in session.artifacts if a.what == str(world.home / "projects" / world.enc1 / f"{CONV_A}.jsonl")]
    assert top and top[0].action != REPORT


def test_red_control_without_the_container_walk(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_folders, "MAX_NEST", 1)
    session, project = _inventories(world)
    missing = _uncovered(_vault_paths(world), project)
    assert str(world.cases["nested_2"]) in missing or str(world.cases["nested_notes"]) in missing
