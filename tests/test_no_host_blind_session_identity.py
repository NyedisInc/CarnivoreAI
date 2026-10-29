
from __future__ import annotations

import ast
import re
from typing import Optional, Set, Tuple

from tests.test_no_name_keyed_session_identity import SRC, TABLE_RE, _literal_sql

SOCKET_EQ_RE = re.compile(r"\btmux_socket\s*=\s*\?", re.IGNORECASE)

SCOPE_CALL = "host_scope"

Key = Tuple[str, str]

REGISTER = {
    ("src/core/db_steps.py", "_v9_merge_rename_splits"): (
        "PERMANENT. The v8 -> v9 migration step, which runs at schema v9, "
        "31 versions before host_key exists. Every row it touches is local."
    ),
}

CONVERTED = {
    ("src/core/session_store.py", "get_instance"),
    ("src/core/activity_persist.py", "write_state"),
    ("src/core/session_restart.py", "rebind_instance"),
    ("src/core/session_instance_index.py", "build_instance_index"),
    ("src/core/session_agent_infer_apply.py", "_row_gate"),
    ("src/core/session_agent_provenance.py", "stored_launch_for"),
    ("src/core/session_fork.py", "resolve_fork_source"),
    ("src/core/session_fork.py", "newest_anchor_uuid"),
    ("src/core/session_identity.py", "claim_instance"),
    ("src/core/session_import_promote.py", "_row_exists"),
    ("src/core/session_import_promote.py", "promote_to_created"),
    ("src/core/session_import_promote.py", "record_decline"),
    ("src/core/session_import_promote.py", "attribution_settled_instances"),
    ("src/core/session_import_promote.py", "reexaminable_instances"),
    ("src/core/session_import_promote.py", "declined_instances"),
    ("src/core/session_instance_rekey.py", "reconcile_instance_epoch"),
    ("src/core/session_label.py", "set_label_for_instance"),
    ("src/core/session_label.py", "label_for_instance"),
    ("src/core/session_label.py", "label_for_name"),
    ("src/core/session_lifecycle.py", "_running_candidates"),
    ("src/core/session_status_seed_read.py", "read_instance_row"),
    ("src/core/session_store.py", "owned_instances"),
    ("src/core/session_store.py", "identity_for_instance"),
    ("src/core/session_store.py", "identity_for_live_name"),
    ("src/core/session_work_stamp.py", "resolve_instance_row"),
}


def _calls(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)
        for n in ast.walk(node)
    )


def scan_source(text: str, relpath: str) -> Tuple[Set[Key], Set[Key]]:
    blind: Set[Key] = set()
    scoped: Set[Key] = set()

    def visit(node: ast.AST, func: Optional[ast.AST]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute" and node.args):
            sql = _literal_sql(node.args[0])
            if sql and TABLE_RE.search(sql):
                upper = sql.upper()
                where = sql[upper.find("WHERE"):] if "WHERE" in upper else ""
                if SOCKET_EQ_RE.search(where):
                    key = (relpath, getattr(func, "name", "<module>"))
                    (scoped if func is not None and _calls(func, SCOPE_CALL) else blind).add(key)
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(ast.parse(text), None)
    return blind, scoped


def _scan_src() -> Tuple[Set[Key], Set[Key]]:
    blind: Set[Key] = set()
    scoped: Set[Key] = set()
    for path in sorted(SRC.rglob("*.py")):
        b, s = scan_source(path.read_text(encoding="utf-8"), str(path.relative_to(SRC.parent)))
        blind |= b
        scoped |= s
    return blind, scoped


def test_the_scan_sees_the_converted_readers_as_scoped():
    blind, scoped = _scan_src()
    assert len(blind) + len(scoped) >= len(REGISTER) + len(CONVERTED)
    assert CONVERTED <= scoped, CONVERTED - scoped


def test_every_host_blind_socket_statement_is_registered_and_nothing_stale_is():
    blind, _ = _scan_src()
    assert sorted(blind - set(REGISTER)) == [], "scope these with host_scope, or register why not"
    assert sorted(set(REGISTER) - blind) == [], "converted or gone: remove from the register"


def test_the_scan_can_go_red():
    source = '''
def blind(conn):
    conn.execute("SELECT id FROM sessions WHERE tmux_socket = ? AND tmux_name = ?", ("s", "n"))

def scoped(conn):
    sql, params = host_scope(conn)
    conn.execute(f"SELECT id FROM sessions WHERE tmux_socket = ? AND tmux_name = ?{sql}", ("s", "n"))

def other_table(conn):
    conn.execute("SELECT 1 FROM layouts WHERE tmux_socket = ?", ("s",))
'''
    blind, scoped = scan_source(source, "x.py")
    assert blind == {("x.py", "blind")}
    assert scoped == {("x.py", "scoped")}
