from __future__ import annotations

import ast
import inspect
import textwrap
import typing

import pytest

from src.core.attention import manager_port
from src.core.session_manager import SessionManager
from src.core.sessions.registry import SessionRegistry
from src.core.sessions.toast_inbox import ToastInbox

PORTS = {
    manager_port.SideEffectsManager: SessionManager,
    manager_port.AttentionManager: SessionManager,
    manager_port._BackendRegistry: SessionRegistry,
    manager_port._ToastInbox: ToastInbox,
}


def _own_members(protocol: type) -> tuple[list[str], list[str]]:
    methods = [n for n, v in vars(protocol).items() if inspect.isfunction(v) and not n.startswith("__")]
    attrs = [n for n in vars(protocol).get("__annotations__", {})]
    return attrs, methods


def _assigned_on_self(cls: type) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls.__init__)))
    return {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
        and isinstance(node.value, ast.Name) and node.value.id == "self"
    }


def _params(fn) -> set[str]:
    return set(inspect.signature(fn).parameters) - {"self"}


@pytest.mark.parametrize("protocol", list(PORTS), ids=lambda p: p.__name__)
def test_every_port_member_exists_on_the_live_class(protocol):
    live = PORTS[protocol]
    attrs, methods = _own_members(protocol)
    assert attrs or methods, "the port declares nothing: the test would pass on nothing"
    assigned = _assigned_on_self(live)
    for name in attrs:
        assert hasattr(live, name) or name in assigned, f"{live.__name__} lost attribute {name}"
    for name in methods:
        impl = getattr(live, name, None)
        assert impl is not None, f"{live.__name__} lost method {name}"
        missing = _params(getattr(protocol, name)) - _params(impl)
        assert not missing, f"{live.__name__}.{name} lost parameters {sorted(missing)}"


def test_the_nested_port_types_cover_the_members_wiring_uses():
    hints = typing.get_type_hints(manager_port.SideEffectsManager)
    assert hints["_registry"] is manager_port._BackendRegistry
    attrs, methods = _own_members(manager_port._BackendRegistry)
    assert {"backends", "sessions"} <= set(attrs) and "listable_ids" in methods
