
from __future__ import annotations

import ast
import re
import pathlib
from dataclasses import dataclass
from typing import List, Optional

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
DB_MODELS = SRC / "core" / "db_models.py"

TABLE_RE = re.compile(r"\b(FROM|UPDATE)\s+sessions\b", re.IGNORECASE)

NAME_EQ_RE = re.compile(r"tmux_name\s*=\s*\?", re.IGNORECASE)

EPOCH_EQ_RE = re.compile(r"tmux_created_epoch\s*=\s*\?", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:

    path: pathlib.Path
    lineno: int
    func: str
    sql: str

    @property
    def key(self) -> tuple:
        return (str(self.path.relative_to(SRC.parent)), self.func)


def _literal_sql(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_sql(node.left)
        right = _literal_sql(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _iter_execute_calls(tree: ast.Module):
    results: List[tuple] = []

    def visit(node: ast.AST, stack: List[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack = stack + [node.name]
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "execute":
                results.append((node.lineno, stack[-1] if stack else "<module>", node))
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    visit(tree, [])
    return results


def _scan_file(path: pathlib.Path) -> List[Violation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: List[Violation] = []
    for lineno, func, call in _iter_execute_calls(tree):
        if not call.args:
            continue
        sql = _literal_sql(call.args[0])
        if not sql:
            continue
        if not TABLE_RE.search(sql):
            continue
        where_idx = sql.upper().find("WHERE")
        where_clause = sql[where_idx:] if where_idx != -1 else ""
        if not NAME_EQ_RE.search(where_clause):
            continue
        if EPOCH_EQ_RE.search(where_clause):
            continue
        found.append(Violation(path=path, lineno=lineno, func=func, sql=sql))
    return found


def find_violations(root: pathlib.Path = SRC) -> List[Violation]:
    out: List[Violation] = []
    for path in sorted(root.rglob("*.py")):
        out.extend(_scan_file(path))
    out.sort(key=lambda v: (str(v.path), v.lineno))
    return out


EXEMPTIONS = {
    (
        "src/core/session_group_membership_migrate.py",
        "resolve_session_uuid",
    ): (
        "THE BOUNDARY, not a lookup that could be keyed better. It is the "
        "ONE place a tmux name becomes a durable session_uuid, and it "
        "exists because the sidebar addresses its rows by name while the "
        "v24 membership table keys on session_uuid; the guess is now made "
        "once, explicitly, with a stated rule (running row, else newest) "
        "instead of being frozen into a primary key on every row of "
        "session_group_members. The blast radius is bounded: the wrong "
        "answer files a conversation in a group, which is user-visible, "
        "reversible with one drag, and touches no lifecycle, no lineage "
        "and no conversation. The instance triple is not available here - "
        "the caller has a name and nothing else."
    ),
    (
        "src/core/session_store.py",
        "identity_for_live_name",
    ): (
        "KNOWN BUG, unfixed by this guard. Returns id + parent_session_id "
        "for the newest row sharing a name, and the result reaches the "
        "client - exactly the class this file exists to stop the NEXT "
        "instance of. Its own docstring already says the guarantee is "
        "weaker than an exact key."
    ),
    (
        "src/core/session_fork.py",
        "resolve_fork_source",
    ): (
        "KNOWN BUG, unfixed by this guard. Finds the row to fork FROM by "
        "newest-row-for-name; a forked session's parent can be resolved "
        "to the wrong session if the name was reused."
    ),
    (
        "src/core/session_fork.py",
        "newest_anchor_uuid",
    ): (
        "KNOWN BUG, unfixed by this guard. Finds the row a fork just "
        "created by newest-row-for-name, to stamp lineage onto it; a "
        "reused name can stamp lineage onto the wrong row."
    ),
    (
        "src/core/session_manager.py",
        "claude_uuid_for_tmux_name",
    ): (
        "KNOWN BUG, unfixed by this guard. Resolves the Claude conversation "
        "uuid to push an out-of-band rename into by newest-row-for-name; a "
        "reused name can push the rename into the wrong conversation. "
        "session_manager.py is excluded from edits by this task - flagged "
        "here, not fixed here."
    ),
    (
        "src/core/session_label.py",
        "label_for_name",
    ): (
        "ALLOWED, not debt. Reads ONLY the title/label for display - never "
        "an id, a uuid, or anything used to decide which row IS the "
        "session or to write durable state. This is exactly the "
        "'deriving a display label from it' carve-out this guard's own "
        "spec names session_label.py for. Its own docstring already "
        "documents the one gap it cannot cover (a live external session "
        "with no row at all) and points callers at the instance-keyed "
        "sibling wherever an epoch is available."
    ),
    (
        "src/core/automations/run_by.py",
        "session_name",
    ): (
        "ALLOWED, display only (cf8721356, item 542, #1701). Reads ONLY the "
        "title columns, once, when an agent presses run now, to word 'run "
        "now by <session>' in the run's notes. It never returns an id and "
        "decides no row and writes no session state; the pressing agent is "
        "live, so its row is the newest one under its name. Same carve-out "
        "as session_label.label_for_name."
    ),
    (
        "src/core/inventory/identity.py",
        "other_rows_named",
    ): (
        "ALLOWED, a count not a pick. It asks how many OTHER rows carry this "
        "row's tmux name so a name-keyed store is reported as shared and "
        "kept; it never chooses a row, and the row itself is already "
        "resolved by id."
    ),
}


def test_no_new_name_keyed_sessions_identity_lookup():
    found = find_violations()
    found_keys = {v.key for v in found}
    unregistered = [v for v in found if v.key not in EXEMPTIONS]
    assert not unregistered, (
        "new (or newly regressed) sessions-row identity lookup(s) keyed on "
        "tmux_name alone, with no exact tmux_created_epoch to anchor them:\n"
        + "\n".join(
            f"  {v.path.relative_to(SRC.parent)}:{v.lineno} "
            f"in {v.func}() - {v.sql[:160]!r}"
            for v in unregistered
        )
        + "\n\nA tmux name is reused every time a session is recreated "
        "after its pane dies, so 'the newest row with this name' is a "
        "guess, not identity. Key the lookup on the instance triple "
        "(tmux_socket, tmux_name, tmux_created_epoch) or on "
        "claude_session_uuid/session_uuid instead. If this read is "
        "genuinely display-only (a label, never used to decide which row "
        "IS the session), register it in EXEMPTIONS in "
        "tests/test_no_name_keyed_session_identity.py with a one-line "
        "reason instead of fixing it."
    )

    stale = sorted(set(EXEMPTIONS) - found_keys)
    assert not stale, (
        "exemption(s) registered for a site this scan no longer finds - "
        "the function was fixed, renamed, or removed, and the entry is "
        "now dead weight:\n"
        + "\n".join(f"  {path}::{func}" for path, func in stale)
        + "\n\nRemove the stale entry from EXEMPTIONS (or, if it was "
        "fixed, celebrate and remove it)."
    )


def test_the_guard_can_actually_fail():
    import tempfile

    src = (
        "import sqlite3\n\n"
        "def resolve_by_name_only(conn, name):\n"
        "    return conn.execute(\n"
        "        \"SELECT id FROM sessions WHERE tmux_name = ? \"\n"
        "        \"AND tmux_created_epoch IS NOT NULL \"\n"
        "        \"ORDER BY tmux_created_epoch DESC LIMIT 1\",\n"
        "        (name,),\n"
        "    ).fetchone()\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        planted = tmp_path / "planted_violation.py"
        planted.write_text(src, encoding="utf-8")
        found = find_violations(root=tmp_path)
    assert len(found) == 1, (
        f"expected exactly one planted violation, scanner found {len(found)}"
    )
    assert found[0].func == "resolve_by_name_only"


def test_epoch_exact_match_is_not_flagged():
    import tempfile

    src = (
        "import sqlite3\n\n"
        "def resolve_by_instance_triple(conn, socket, name, epoch):\n"
        "    return conn.execute(\n"
        "        \"SELECT id FROM sessions WHERE tmux_socket = ? \"\n"
        "        \"AND tmux_name = ? AND tmux_created_epoch = ?\",\n"
        "        (socket, name, epoch),\n"
        "    ).fetchone()\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        (tmp_path / "safe.py").write_text(src, encoding="utf-8")
        found = find_violations(root=tmp_path)
    assert found == []


def test_group_membership_primary_key_is_a_known_bad_contract():
    ddl_text = DB_MODELS.read_text(encoding="utf-8")
    match = re.search(
        r"DDL_SESSION_GROUP_MEMBERS\s*=\s*\"\"\"(.*?)\"\"\"",
        ddl_text,
        re.DOTALL,
    )
    assert match is not None, (
        "src/core/db_models.py no longer defines DDL_SESSION_GROUP_MEMBERS "
        "- this test needs updating, but first confirm the group "
        "membership table's key was not just silently changed underneath "
        "it without anyone reading this test."
    )
    table_sql = match.group(1)
    assert re.search(r"tmux_name\s+TEXT\s+PRIMARY\s+KEY", table_sql, re.IGNORECASE), (
        "the RETIRED v8 session_group_members table was edited. Schema "
        "v24 superseded it with session_group_membership and every "
        "migration step in this project is additive, so the old table is "
        "supposed to sit there unread and unchanged. If you meant to "
        "retire it for real, that is a schema decision with a rollback "
        "consequence - read src/core/db_steps.py's docstring first."
    )


def test_group_membership_is_now_keyed_on_durable_identity():
    ddl_text = DB_MODELS.read_text(encoding="utf-8")
    match = re.search(
        r"DDL_SESSION_GROUP_MEMBERSHIP\s*=\s*\"\"\"(.*?)\"\"\"",
        ddl_text,
        re.DOTALL,
    )
    assert match is not None, (
        "src/core/db_models.py no longer defines DDL_SESSION_GROUP_MEMBERSHIP "
        "- the v24 membership table. Confirm the durable key was not "
        "removed before updating this test."
    )
    table_sql = match.group(1)
    assert re.search(
        r"session_uuid\s+TEXT\s+PRIMARY\s+KEY", table_sql, re.IGNORECASE
    ), (
        "session_group_membership no longer keys on session_uuid. A tmux "
        "name is not durable identity - see this module's docstring."
    )
    assert re.search(r"\bposition\s+INTEGER\b", table_sql, re.IGNORECASE), (
        "session_group_membership lost its `position` column, which is "
        "the durable order within a group."
    )
