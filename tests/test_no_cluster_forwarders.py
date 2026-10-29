
from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "src" / "core" / "session_manager.py"

SHIPPED_COLLABORATORS = {
    "_probe_health",
    "_theme_store",
    "_toast_inbox",
    "_registry",
    "_sidecars",
    "_owned",
}

DELETED_FORWARDERS = {
    "pinned_themes",
    "_theme_accent_cache",
    "_pending_toasts",
    "_pending_startup_toasts",
    "log_buffers",
    "command_counts",
    "idle_watchers",
    "adopt_fifo_offsets",
    "pending_terminal_commands",
    "_load_pinned_themes",
    "_save_pinned_themes",
    "get_pinned_theme",
    "discard_pinned_theme",
    "get_project_theme",
    "set_project_theme",
    "resolve_project_theme",
    "_get_theme_accent_color",
    "_prune_toasts",
    "ack_toast",
    "get_toasts",
    "last_probe_health",
    "owned_tmux_sessions",
    "_legacy_metadata_needs_backfill",
    "_boot_listing",
    "_write_metadata_atomic",
    "_owned_instances_from_db",
    "owned_tmux_instances",
    "is_owned_tmux_name",
    "current_session",
    "current_backend",
    "session",
    "backend",
    "get_session",
    "get_backend",
    "list_sessions",
    "_resolve_session_id",
    "_register_session",
    "_registered_ids_for_tmux_name",
    "subscribe_output",
    "unsubscribe_output",
}

DELETED_ATTRIBUTES = {
    "sessions",
    "backends",
    "_subscribers",
    "_last_session_id",
}


def _manager_class() -> ast.ClassDef:
    tree = ast.parse(MANAGER.read_text(encoding="utf-8"), filename=str(MANAGER))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SessionManager"
    )


def _self_attribute_root(value: ast.expr) -> str | None:
    chain: list[str] = []
    while isinstance(value, ast.Attribute):
        chain.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name) and value.id == "self" and chain:
        return chain[-1]
    return None


def _forwarders() -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for node in _manager_class().body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if len(body) != 1:
            continue
        statement = body[0]
        if isinstance(statement, ast.Return) and statement.value is not None:
            value: ast.expr = statement.value
        elif isinstance(statement, ast.Expr):
            value = statement.value
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            value = statement.targets[0]
        else:
            continue
        target = value.func if isinstance(value, ast.Call) else value
        root = _self_attribute_root(target)
        if root in SHIPPED_COLLABORATORS:
            start = node.lineno
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list)
            found.append((node.name, root, node.end_lineno - start + 1))
    return found


def test_the_manager_class_is_still_parsable_and_present():
    cls = _manager_class()
    members = [n.name for n in cls.body if isinstance(n, ast.FunctionDef)]

    assert len(members) > 50, (
        f"SessionManager holds only {len(members)} methods; the walk below "
        "may be reporting on the wrong thing"
    )


def test_no_member_forwards_to_a_shipped_collaborator():
    offenders = _forwarders()

    assert offenders == [], (
        "SessionManager forwards to a shipped collaborator: "
        + ", ".join(f"{name} -> self.{root} ({n} lines)" for name, root, n in offenders)
        + ". Point the caller at the collaborator instead."
    )


def test_a_deleted_forwarder_is_not_revived():
    members = {
        node.name
        for node in _manager_class().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def check(name: str) -> None:
        assert name not in members, (
            f"SessionManager.{name} is back; it was deleted by the slice that "
            "extracted its cluster, and its callers hold the collaborator now"
        )

    assert_no_offenders("deleted forwarder not revived",
                        sorted(DELETED_FORWARDERS), check)


def test_a_moved_container_is_not_re_created_on_the_manager():
    init = next(
        node
        for node in _manager_class().body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assigned: set[str] = set()
    for node in ast.walk(init):
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                assigned.add(target.attr)

    def check(name: str) -> None:
        assert name not in assigned, (
            f"SessionManager.__init__ creates self.{name} again; the registry "
            "owns that container and a second one holding the same logical "
            "state is the 22-rows-for-21-panes defect"
        )

    assert_no_offenders("moved container not re-created",
                        sorted(DELETED_ATTRIBUTES), check)
