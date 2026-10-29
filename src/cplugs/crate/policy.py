
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs

CARRY, EXCLUDE, DERIVED, BLOCKED = "carry", "exclude", "derived", "blocked"
OPTIONAL = "optional"
OWN, SHARE = cf.constants.VARIANT_OWN, cf.constants.VARIANT_SHARE
HOME_CLAUDE, HOME_CODEX, HOME_STATE = cf.constants.HOME_CLAUDE, cf.constants.HOME_CODEX, cf.constants.HOME_STATE

R_TRANSCRIPT, R_SUBAGENT, R_TOOL_RESULT, R_CONV_FILE = "transcript", "subagent", "tool_result", "conversation_file"
R_FILE_HISTORY, R_TODO, R_MEMORY, R_NOTE, R_ORPHAN = "file_history", "todo", "memory", "project_note", "orphan_transcript"
R_ROLLOUT, R_TASK_FILE, R_DESK, R_PLAN = "codex_rollout", "task_file", "swarm_desk", "plan"
R_SET_ASIDE, R_CONFLICT, R_ARCHIVED = "set_aside_transcript", "conflict_copy", "archived_copy"
R_PROJECT_FILE, R_PROJECT_LINK = cf.constants.ROLE_PROJECT_FILE, cf.constants.ROLE_PROJECT_LINK
HOME_PROJECT = cf.constants.HOME_PROJECT
R_PLUGIN_FILE = cf.constants.ROLE_PLUGIN_FILE
HOME_PLUGIN_PREFIX = cf.constants.HOME_PLUGIN_PREFIX
_DECLARED_ACTION = {"carried": CARRY, "derived": DERIVED, "excluded": EXCLUDE}
COPY_ROLES: Tuple[str, ...] = (R_SET_ASIDE, R_CONFLICT, R_ARCHIVED)
MAIN_ROLES: Tuple[str, ...] = (R_TRANSCRIPT, R_ROLLOUT, R_ORPHAN)
FOLDER_CONVERSATION = "conversation_folder"

_KEEP_OUT = "environment captures and debug traces can hold tokens, and a resume does not need them"
_SHARE_ONLY_CONVERSATION = "a share carries only the conversation itself"
_V1_NO_HISTORY = "legacy restore points and the vault's own record are not carried in v1"


@dataclass(frozen=True)
class Rule:

    own: str
    share: str
    reason: str


@dataclass(frozen=True)
class Decision:

    action: str
    role: Optional[str]
    reason: str
    key: str = ""


def _rows(stores: Sequence[str]) -> Dict[str, Rule]:
    return {f"rows/{s}": Rule(CARRY, EXCLUDE, "every claimed row, secret columns left out; a share carries no rows in v1")
            for s in stores}


_ENTRY_STORES = (cs.UNREAD_STORE, cs.CONFIG_STORE, cs.CLAUDE_JSON_STORE, cs.PREFERENCES, cs.JOURNAL, cs.PINNED_THEMES_FILE)

POLICY: Dict[str, Rule] = {
    "claude/transcript": Rule(CARRY, CARRY, "the conversation; a share is redacted"),
    f"claude/{FOLDER_CONVERSATION}": Rule(CARRY, CARRY, "the conversation's own folder: subagents, tool results"),
    "claude/set_aside_transcript": Rule(CARRY, EXCLUDE, "a transcript Claude set aside; " + _SHARE_ONLY_CONVERSATION),
    "claude/conflict_copy": Rule(CARRY, EXCLUDE, "an iCloud conflict copy, carried and named in a warning"),
    "claude/archived_copy": Rule(CARRY, EXCLUDE, "a copy of the conversation in an archive folder under projects/"),
    "claude/file_history": Rule(CARRY, EXCLUDE, "the edit history of files the conversation touched"),
    "claude/todo": Rule(CARRY, EXCLUDE, "the conversation's todo list"),
    "claude/plan": Rule(CARRY, EXCLUDE, "a plan file a carried transcript names"),
    "claude/session_env": Rule(EXCLUDE, EXCLUDE, _KEEP_OUT),
    "claude/debug": Rule(EXCLUDE, EXCLUDE, _KEEP_OUT),
    "claude/pid_registry": Rule(EXCLUDE, EXCLUDE, "the live process registry of Claude Code"),
    "claude/history_lines": Rule(CARRY, EXCLUDE, "the matching lines of Claude's prompt history, byte exact"),
    "codex/codex_rollout": Rule(CARRY, CARRY, "the Codex conversation; a share is redacted"),
    "codex/shell_snapshot": Rule(EXCLUDE, EXCLUDE, "a shell environment capture"),
    "codex/index_lines": Rule(CARRY, EXCLUDE, "the matching lines of Codex's thread index, byte exact"),
    f"{cs.STORE_MEMORY}/memory": Rule(CARRY, EXCLUDE, "Claude's notes for the project"),
    f"{cs.STORE_MEMORY}/project_note": Rule(CARRY, EXCLUDE, "a loose notes file or merged side folder of the project"),
    f"{cs.STORE_ORPHANS}/orphan_transcript": Rule(CARRY, EXCLUDE, "a conversation in the project's folder no session names"),
    f"{cs.STORE_ORPHANS}/{FOLDER_CONVERSATION}": Rule(CARRY, EXCLUDE, "the folder of a conversation no session names"),
    f"{cs.STORE_ORPHANS}/set_aside_transcript": Rule(CARRY, EXCLUDE, "a set-aside copy of an unnamed conversation"),
    f"{cs.STORE_ORPHANS}/conflict_copy": Rule(CARRY, EXCLUDE, "an iCloud conflict copy, carried and named in a warning"),
    f"{cs.STORE_TASK_FILES}/task_file": Rule(CARRY, EXCLUDE, "files attached to the scope's Task Manager items"),
    f"{cs.STORE_DESK}/swarm_desk": Rule(CARRY, EXCLUDE, "a Swarm agent's desk notes, carried as opaque files"),
    f"{cs.STORE_THEME_DOTFILE}/entry": Rule(CARRY, EXCLUDE, "the folder's theme, carried as text in entries.json"),
    f"{cs.STORE_POINTS}/*": Rule(EXCLUDE, EXCLUDE, _V1_NO_HISTORY),
    f"{cs.STORE_VAULT}/*": Rule(OPTIONAL, EXCLUDE, "the conversation's backup points; carried when include backups is ticked (own crates only), "
                                "the vault's own record is never carried"),
    f"{cs.STORE_FOLDER}/*": Rule(EXCLUDE, EXCLUDE, "the project's code folder: project_pack carries code (an own copy "
                                  "carries the files only on include_project_files)"),
    f"{cs.STORE_PIPE}/*": Rule(DERIVED, DERIVED, "the pane's raw output log, keyed by tmux name"),
    f"{cs.STORE_BACKUP_COPIES}/*": Rule(DERIVED, DERIVED, "deep search's disposable copies"),
    f"{cs.STORE_SWARM_SETTINGS}/*": Rule(DERIVED, DERIVED, "rewritten at each agent launch"),
    f"{cs.STORE_SWARM_HOOKS}/*": Rule(DERIVED, DERIVED, "rebuilt at each agent launch"),
    **_rows([cs.MAIN_STORE, *sorted(cs.SIDE_DBS)]),
    **{f"entry/{s}": Rule(CARRY, EXCLUDE, "the scope's entry; a share carries no entries in v1") for s in _ENTRY_STORES},
    f"entry/{cs.RENAME_STORE}": Rule(DERIVED, DERIVED, "the title sync's retry budget, rebuilt on the next rename"),
    "entry/ui_preferences.foreign_tab": Rule(EXCLUDE, EXCLUDE, "a tab inside another session's grid; that grid is its session's"),
}


@dataclass(frozen=True)
class HomesView:

    claude: Tuple[str, ...]
    codex: str
    state: str

    @classmethod
    def of(cls, locations: cs.Locations) -> "HomesView":
        return cls(tuple(os.path.realpath(str(h)) for h in locations.claude_homes()),
                   os.path.realpath(str(locations.codex_home())), os.path.realpath(str(locations.state_dir)))

    def _homes(self) -> List[Tuple[str, int, str]]:
        homes = [(HOME_CLAUDE, i, h) for i, h in enumerate(self.claude)] + [(HOME_CODEX, 0, self.codex),
                                                                         (HOME_STATE, 0, self.state)]
        return sorted(homes, key=lambda h: -len(h[2]))

    def place(self, path: str) -> Optional[Tuple[str, int, str]]:
        homes = self._homes()
        real_homes = {h[2].rstrip(os.sep): h for h in homes}
        lexical = os.path.normpath(os.path.abspath(path))
        ancestor = os.path.dirname(lexical)
        while ancestor and ancestor != os.path.dirname(ancestor):
            found = real_homes.get(os.path.realpath(ancestor).rstrip(os.sep))
            if found is not None:
                return found[0], found[1], Path(os.path.relpath(lexical, ancestor)).as_posix()
            ancestor = os.path.dirname(ancestor)
        real = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
        for kind, index, home in homes:
            if real.startswith(home.rstrip(os.sep) + os.sep):
                return kind, index, Path(os.path.relpath(real, home)).as_posix()
        return None


def _projects_role(rel_parts: Sequence[str], is_dir: bool, orphan: bool) -> Optional[str]:
    found = cs.conversation_form(rel_parts[-1], is_dir)
    if found is None:
        return None
    nested = len(rel_parts) > 3
    form = found[1]
    if form == cs.FORM_SET_ASIDE:
        return R_SET_ASIDE
    if form == cs.FORM_CONFLICT:
        return R_CONFLICT
    if nested:
        return R_ARCHIVED
    if form == cs.FORM_FOLDER:
        return FOLDER_CONVERSATION
    return R_ORPHAN if orphan else R_TRANSCRIPT


def _claude_role(rel: str, is_dir: bool, orphan: bool = False) -> Optional[str]:
    parts = rel.split("/")
    top = parts[0]
    if top == "projects" and len(parts) >= 3:
        return _projects_role(parts, is_dir, orphan)
    return {"todos": R_TODO, "file-history": R_FILE_HISTORY, "session-env": "session_env", "debug": "debug",
            "sessions": "pid_registry", "plans": R_PLAN}.get(top)


def _memory_role(rel: str) -> str:
    return R_MEMORY if rel.split("/")[-1] == "memory" else R_NOTE


def classify(art: cs.Artifact, homes: HomesView) -> Tuple[str, Optional[str]]:
    if art.locator.get("plugin"):
        return f"plugin/{art.store}", R_PLUGIN_FILE
    if art.kind == cs.KIND_ROWS:
        return f"rows/{art.store}", None
    if art.kind == cs.KIND_ENTRY:
        if art.store == cs.PREFERENCES and art.locator.get("key") == "ui_preferences.values.terminal_layouts.sessions":
            return "entry/ui_preferences.foreign_tab", None
        return f"entry/{art.store}", None
    if art.kind == cs.KIND_LINES:
        return ("claude/history_lines" if art.store == "claude" else f"{art.store}/index_lines"), None
    if art.store == cs.STORE_THEME_DOTFILE:
        return f"{cs.STORE_THEME_DOTFILE}/entry", None
    path = str(art.locator.get("path") or art.what)
    is_dir = art.kind == cs.KIND_DIR
    placed = homes.place(path)
    if art.store in ("claude", cs.STORE_ORPHANS, cs.STORE_MEMORY):
        if placed is None or placed[0] != HOME_CLAUDE:
            return f"{art.store}/outside", None
        if art.store == cs.STORE_MEMORY:
            role = _memory_role(placed[2])
            return f"{art.store}/{role}", role
        role = _claude_role(placed[2], is_dir, orphan=art.store == cs.STORE_ORPHANS)
        if role is None:
            return f"{art.store}/unknown", None
        return f"{art.store}/{role}", None if role == FOLDER_CONVERSATION else role
    if art.store == "codex":
        top = placed[2].split("/")[0] if placed and placed[0] == HOME_CODEX else ""
        role = {"sessions": R_ROLLOUT, "archived_sessions": R_ROLLOUT, "shell_snapshots": "shell_snapshot"}.get(top)
        return (f"codex/{role}", role) if role else ("codex/unknown", None)
    if art.store == cs.STORE_TASK_FILES:
        return f"{art.store}/task_file", R_TASK_FILE
    if art.store == cs.STORE_DESK:
        return f"{art.store}/swarm_desk", R_DESK
    return f"{art.store}/*", None


def decide_plugin(art: cs.Artifact, variant: str) -> Decision:
    loc, key = art.locator, f"plugin/{art.store}"
    if loc.get("undeclared"):
        return Decision(BLOCKED, None, f"no crate policy for {art.store}: {art.reason}", key)
    declared = loc["policy"]
    action = _DECLARED_ACTION.get(declared["own" if variant == OWN else "share"], BLOCKED)
    reason = declared["reason"]
    if action != CARRY:
        return Decision(action, None, reason, key)
    if loc.get("unset"):
        return Decision(EXCLUDE, None, f"its setting {loc['unset']} is not set, so this store has no location yet", key)
    if loc.get("install_scoped"):
        return Decision(EXCLUDE, None, f"scoped to this install, never carried: {reason}", key)
    if loc.get("unscopable"):
        return Decision(BLOCKED, None, f"{art.store} is a {loc['decl_kind']} that cannot be cut by {loc['scope_by']}; it needs row or entry claims before it can be carried", key)
    return Decision(CARRY, R_PLUGIN_FILE, reason, key)


def decide(art: cs.Artifact, variant: str, homes: HomesView, include_backups: bool = False) -> Decision:
    if art.locator.get("plugin"):
        return decide_plugin(art, variant)
    key, role = classify(art, homes)
    if art.derived:
        return Decision(DERIVED, role, art.reason or "rebuilt from other data, never copied", key)
    rule = POLICY.get(key)
    if rule is None:
        return Decision(BLOCKED, role, f"no crate policy for {key}", key)
    action = rule.own if variant == OWN else rule.share
    if action == OPTIONAL:
        return Decision(CARRY if include_backups else EXCLUDE, role, rule.reason if include_backups else f"optional, not ticked: {rule.reason}", key)
    return Decision(action, role, rule.reason, key)


def file_role(folder_role: Optional[str], sub: str) -> str:
    if folder_role is not None:
        return folder_role
    parts = sub.split("/")
    if parts[0] == "subagents" and parts[-1].endswith(".jsonl"):
        return R_SUBAGENT
    if parts[0] == "tool-results":
        return R_TOOL_RESULT
    return R_CONV_FILE


def line_mode(role: str, name: str) -> bool:
    consts = cf.constants
    return role in consts.LINE_ROLES and (role != R_ORPHAN or ".jsonl" in name) or (
        role in consts.LINE_ROLES_WHEN_JSONL and ".jsonl" in name)



def conversation_for(role: Optional[str], path: str, is_dir: bool, scope_ids: Sequence[str]) -> Optional[str]:
    """The conversation an artifact belongs to, read from its own name: a transcript, copy or conversation folder by the
    layout rule, a file-history folder by its name, a todo or a Codex rollout by the scope id its name carries. Pure.

    Inputs: role (the artifact's role; None for a conversation folder); path (the artifact's path); is_dir; scope_ids
      (every conversation id in scope). Output: the id, or None for a file that belongs to no conversation.
    Example: conversation_for('todo', '/h/todos/c1-agent-c1.json', False, ['c1']) -> 'c1'
    """
    name = os.path.basename(path)
    if role in (None, R_TRANSCRIPT, R_ORPHAN, *COPY_ROLES):
        found = cs.conversation_form(name, is_dir)
        return found[0] if found else None
    if role == R_FILE_HISTORY:
        return name
    if role == R_TODO:
        hits = [c for c in scope_ids if name.startswith(c + "-")]
        return max(hits, key=len) if hits else None
    if role == R_ROLLOUT:
        return next((c for c in scope_ids if name.endswith(f"-{c}.jsonl")), None)
    return None
