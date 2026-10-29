
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Tuple

from src.core.claude_transcript_correlate import slugify_project_dir
from tests.python.inventory.world import (A, B, CONV_A, CONV_A0, CONV_B, CONV_D, EPOCH_A, P, TMUX_A, TMUX_B, UUID_A,
                                          UUID_D, write_json, write_text)

LINE = '{"text":"transcript body"}\n'


def mark(w: SimpleNamespace, tags: Tuple[str, ...], store: str, path: Path) -> Path:
    for tag in tags:
        w.ledger.files[(tag, store, str(path))] += 1
    return path


def entry(w: SimpleNamespace, tags: Tuple[str, ...], store: str, what: str) -> None:
    for tag in tags:
        w.ledger.entries[(tag, store, what)] += 1


def seed_claude_and_codex(w: SimpleNamespace) -> None:
    enc1, enc2 = slugify_project_dir(w.root1), slugify_project_dir(w.root2)
    projects = w.home / "projects"
    def claude(tags: Tuple[str, ...], path: Path, listed: Optional[Path] = None) -> None:
        mark(w, tags, "claude", listed or write_text(path, LINE))
        write_text(path, LINE)

    claude((A,), projects / enc1 / f"{CONV_A}.jsonl")
    claude((A,), projects / enc1 / CONV_A / "subagents" / "agent-a1.jsonl", projects / enc1 / CONV_A)
    claude((A,), projects / enc1 / f"{CONV_A0}.jsonl")
    claude((B,), projects / enc1 / f"{CONV_B}.jsonl")
    claude((), projects / enc2 / f"{CONV_D}.jsonl")
    claude((A,), w.home / "todos" / f"{CONV_A}-agent-{CONV_A}.json")
    claude((A,), w.home / "file-history" / CONV_A / "f1", w.home / "file-history" / CONV_A)
    claude((A,), w.home / "session-env" / CONV_A / "e1", w.home / "session-env" / CONV_A)
    claude((A,), w.home / "debug" / f"{CONV_A}.txt")
    registry = w.home / "sessions" / "4242.json"
    write_json(registry, {"sessionId": CONV_A})
    mark(w, (A,), "claude", registry)
    write_json(w.home / "sessions" / "77.json", {"sessionId": CONV_D})
    mark(w, (A,), "codex", write_text(w.codex / "sessions" / "2026" / "10" / "09" / f"rollout-2026-10-09T00-00-00-{CONV_A}.jsonl", LINE))
    mark(w, (A,), "codex", write_text(w.codex / "shell_snapshots" / f"{CONV_A}.sh", "export X=1\n"))
    write_text(w.codex / "shell_snapshots" / f"{CONV_D}.sh", "export X=2\n")
    write_text(w.codex / "session_index.jsonl", f'{{"id":"{CONV_A}","thread_name":"a"}}\n{{"id":"{CONV_D}","thread_name":"d"}}\n')
    write_text(projects / enc1 / "memory" / "MEMORY.md", "# notes\n")
    mark(w, (P,), "claude-memory", projects / enc1 / "memory")
    mark(w, (P,), "claude-orphans", write_text(projects / enc1 / "orphan-conv-0001.jsonl", LINE))
    mark(w, (P,), "claude-orphans", write_text(projects / enc1 / "agent-abc12345.jsonl", LINE))
    write_text(projects / enc2 / "memory" / "MEMORY.md", "# decoy\n")
    w.root1_dir = Path(w.root1)
    w.root1_dir.mkdir(parents=True, exist_ok=True)
    mark(w, (P,), "project-folder", w.root1_dir)


def seed_state_folder_files(w: SimpleNamespace) -> None:
    state = w.state
    point = state / "time-machine" / "unknown" / CONV_A
    write_json(point / "20261016T000000Z-manual" / "meta.json", {"conversation_id": CONV_A, "working_dir": w.root1})
    mark(w, (A,), "time-machine", point)
    write_text(state / "time-machine" / "unknown" / CONV_D / "20261016T000000Z-manual" / "meta.json")
    mark(w, (A,), "deepsearch-backup-copies", write_text(state / "deepsearch-backup-copies" / f"{CONV_A}.abc123def456.jsonl", LINE))
    write_text(state / "deepsearch-backup-copies" / f"{CONV_D}.abc123def456.jsonl", LINE)
    mark(w, (A,), "tmux-pipe-log", write_text(state / f"tmux_{TMUX_A}.pipe", "pane output\n"))
    mark(w, (B,), "tmux-pipe-log", write_text(state / f"tmux_{TMUX_B}.pipe", "pane output\n"))
    files = state / "cplugs" / "huddle" / "files"
    for item, tags in ((w.item_a, (A, P)), (w.item_b, (B, P)), (w.item_p, (P,)), (w.item_d, ())):
        folder = files / str(item)
        write_text(folder / "x.html", "<p>artifact</p>")
        mark(w, tags, "task-manager-files", folder)
    desk = state / "swarm" / "desk"
    for agent, tags in ((1, (A, P)), (2, (P,)), (3, ())):
        folder = desk / str(agent)
        write_text(folder / "desk.md", "# desk\n")
        mark(w, tags, "swarm-desk", folder)
        mark(w, tags, "swarm-settings", write_text(state / "swarm" / "settings" / f"{agent}.json"))
        write_text(state / "swarm" / "hooks" / str(agent) / "commit-msg", "#!/bin/sh\n")
        mark(w, tags, "swarm-hooks", state / "swarm" / "hooks" / str(agent))
    mark(w, (A, B, P), "cc-theme", write_text(Path(w.root1) / ".cc.theme", "acid_trip\n"))
    write_text(Path(w.root2) / ".cc.theme", "dracula\n")


def seed_json_stores(w: SimpleNamespace) -> None:
    unread = w.state / "unread_state.json"
    write_json(unread, {f"row:{w.row_a}": {"auto": True, "manual": False}, f"{TMUX_A}@{EPOCH_A}": {"auto": True, "manual": False},
                        "carnivore_other@1": {"auto": True, "manual": False}})
    entry(w, (A,), "unread_state.json", f"row:{w.row_a}")
    entry(w, (A,), "unread_state.json", f"{TMUX_A}@{EPOCH_A}")
    write_json(w.state / "pinned_themes.json", {TMUX_A: "dracula", "other": "x", f"{TMUX_B}2": f"{TMUX_B}-theme"})
    entry(w, (A,), "pinned_themes.json", TMUX_A)
    folds = [f"p:{w.p1}", f"c:{w.company}", f"p:{w.p2}"]
    write_json(w.config, {"session_account_pins": {UUID_A: "work", UUID_D: "home"}, "ui_preferences": {
        "schema_version": 1, "revision": 1, "values": {
            "drawer_arrangement": {"v": 1, "pinned": [UUID_A, "keep"], "order": [UUID_A], "bands": {"g:x": [UUID_A]},
                                   "collapsed": folds, "mobile": {"collapsed": [f"p:{w.p1}"]}},
            "terminal_layouts": {"v": 1, "sessions": {f"{TMUX_A}:{EPOCH_A}": {"layout": {"v": 1, "rows": [1]}},
                                                       "other:1": {"layout": {"v": 1, "rows": [f"terminal:row:{w.row_a}"]}}}}}}})
    entry(w, (A,), "config.json", f"session_account_pins[{UUID_A}]")
    entry(w, (A,), "ui_preferences", "drawer_arrangement")
    entry(w, (A,), "ui_preferences", f"terminal_layouts[{TMUX_A}:{EPOCH_A}]")
    entry(w, (A,), "ui_preferences", f"terminal:row:{w.row_a} tabs")
    entry(w, (P,), "ui_preferences", f"drawer_arrangement.collapsed[p:{w.p1}]")
    entry(w, (P,), "ui_preferences", f"drawer_arrangement.collapsed[c:{w.company}]")
    entry(w, (P,), "ui_preferences", f"drawer_arrangement.mobile.collapsed[p:{w.p1}]")
    claude_json = w.home / ".claude.json"
    write_json(claude_json, {"projects": {w.root1: {"hasTrustDialogAccepted": True}, w.root2: {"hasTrustDialogAccepted": True}},
                             "oauthAccount": {"emailAddress": "never@read"}})
    entry(w, (P,), ".claude.json", f"{claude_json}#projects[{w.root1}]")
    journal = w.state / "session-journal" / "journal.json"
    write_json(journal, {"schema": 1, "sessions": {"k1": {"session_uuid": UUID_A}, "k2": {"session_uuid": UUID_D}}, "declined": {}, "offer": None})
    entry(w, (A,), "session-journal", str(journal))
    write_json(w.state / "rename-retry" / "marks.json", {"version": 1, "marks": {
        f"{CONV_A}:{w.row_a}": {"agreed_title": "t"}, f"none:{w.row_a}": {"agreed_title": "t"}, f"{CONV_D}:{w.row_d}": {"agreed_title": "d"}}})
    entry(w, (A,), "rename-retry/marks.json", "marks[2 key(s)]")
