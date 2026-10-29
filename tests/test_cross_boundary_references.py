
from __future__ import annotations

import ast
import importlib
import os
import pathlib
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_xbr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_xbr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

PACKAGES = ("src.config", "src.models")

MANAGER_MODULE = "src.core.session_manager"
MANAGER_CLASS = "SessionManager"

ARGUMENT_CONTRACTS = (
    ("src.api.ws_connections", "_resolve_backend", 0),
)

COLLABORATOR_BINDINGS = {
    "services.registry": ("src.core.sessions.registry", "SessionRegistry"),
    "state.session_manager": (MANAGER_MODULE, MANAGER_CLASS),
}


def _python_files():
    return sorted(SRC.rglob("*.py"))


def _package_symbol_imports():
    found = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in PACKAGES:
                for alias in node.names:
                    found.append(
                        (node.module, alias.name, str(path), node.lineno)
                    )
    return found


def _manager_self_attributes():
    path = SRC / "core" / "session_manager.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    attrs: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            attrs.setdefault(node.attr, []).append(node.lineno)
    return attrs


def test_every_package_symbol_import_resolves():
    unresolved = []
    checked = 0
    for module_name, symbol, path, line in _package_symbol_imports():
        module = importlib.import_module(module_name)
        checked += 1
        if not hasattr(module, symbol):
            rel = pathlib.Path(path).relative_to(SRC.parent)
            unresolved.append(f"{rel}:{line}: {module_name}.{symbol}")

    assert checked, "the collector found no imports at all, so it measured nothing"
    assert not unresolved, (
        "these names are imported out of a package that does not export "
        "them:\n  " + "\n  ".join(unresolved)
    )


def test_every_manager_self_attribute_resolves():
    module = importlib.import_module(MANAGER_MODULE)
    manager_class = getattr(module, MANAGER_CLASS)
    instance = manager_class()

    attrs = _manager_self_attributes()
    assert attrs, "the collector found no attributes at all"

    missing = {
        name: lines
        for name, lines in sorted(attrs.items())
        if not (hasattr(instance, name) or hasattr(manager_class, name))
    }
    assert not missing, (
        "these attributes are read off `self` in session_manager.py and do "
        "not exist on the class:\n  "
        + "\n  ".join(
            f"self.{name} (lines {lines[:6]})" for name, lines in missing.items()
        )
    )


def _dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _contract_members(module_path, function_name, arg_index):
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        params = node.args.args
        if arg_index >= len(params):
            return None, set()
        param = params[arg_index].arg
        members = {
            child.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == param
        }
        return param, members
    return None, set()


def _argument_call_sites(function_name, arg_index):
    sites = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bindings = {}
            for node in ast.walk(scope):
                if not isinstance(node, ast.Assign):
                    continue
                dotted = _dotted_name(node.value)
                if not dotted:
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = dotted
            for node in ast.walk(scope):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == function_name
                    and len(node.args) > arg_index
                    and isinstance(node.args[arg_index], ast.Name)
                ):
                    name = node.args[arg_index].id
                    sites.append(
                        (str(path), node.lineno, name, bindings.get(name))
                    )
    return sites


def _resolved_class(binding):
    for tail, (module_name, class_name) in COLLABORATOR_BINDINGS.items():
        if binding == tail or binding.endswith("." + tail):
            return getattr(importlib.import_module(module_name), class_name)
    return None


def test_every_collaborator_argument_carries_the_members_its_callee_uses():
    unresolved = []
    wrong = []
    checked = 0

    for module_name, function_name, arg_index in ARGUMENT_CONTRACTS:
        module_path = SRC.parent / (module_name.replace(".", "/") + ".py")
        param, members = _contract_members(module_path, function_name, arg_index)
        assert members, (
            f"derived no members for {function_name}'s argument {arg_index} "
            f"({param!r}), so this rule would pass without measuring anything"
        )

        for path, line, arg_name, binding in _argument_call_sites(
            function_name, arg_index
        ):
            rel = pathlib.Path(path).relative_to(SRC.parent)
            if binding is None:
                unresolved.append(f"{rel}:{line}: {arg_name} (no binding found)")
                continue
            cls = _resolved_class(binding)
            if cls is None:
                unresolved.append(f"{rel}:{line}: {arg_name} = {binding}")
                continue
            checked += 1
            missing = sorted(m for m in members if not hasattr(cls, m))
            if missing:
                wrong.append(
                    f"{rel}:{line}: {function_name}({arg_name}) gets "
                    f"{cls.__name__} (from {binding}), which has no "
                    + ", ".join(missing)
                )

    assert checked, (
        "no call site resolved to a known collaborator, so this rule "
        "measured nothing. Either COLLABORATOR_BINDINGS is stale or the "
        "call sites moved:\n  " + "\n  ".join(unresolved)
    )
    assert not wrong, (
        "these call sites pass an object that does not carry the members "
        "the callee reads off it:\n  " + "\n  ".join(wrong)
    )


def test_the_collectors_can_actually_fail():
    module = importlib.import_module(MANAGER_MODULE)
    instance = getattr(module, MANAGER_CLASS)()

    assert not hasattr(instance, "_a_name_this_class_has_never_had"), (
        "the planted control name exists, so it proves nothing"
    )
    with pytest.raises(AttributeError):
        getattr(instance, "_a_name_this_class_has_never_had")

    config_module = importlib.import_module("src.config")
    assert not hasattr(config_module, "_a_symbol_this_package_never_exported")

    param, members = _contract_members(
        SRC / "api" / "ws_connections.py", "_resolve_backend", 0
    )
    assert members, "the contract collector derived nothing to check"
    manager_class = getattr(
        importlib.import_module(MANAGER_MODULE), MANAGER_CLASS
    )
    assert [m for m in members if not hasattr(manager_class, m)], (
        f"{MANAGER_CLASS} now carries every member _resolve_backend reads "
        f"off its argument ({sorted(members)}), so passing the manager "
        "there would no longer be detectable and the rule above proves "
        "nothing about which object is passed"
    )
