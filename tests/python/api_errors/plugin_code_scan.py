
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Set

HOST_DIR = Path("src/plugins/host")

CODE_ARG_INDEX: Dict[str, int] = {"_error": 1, "ConsentRefused": 1, "SecretError": 0, "SideloadRefused": 0}

CODE_SHAPE = re.compile(r"[a-z][a-z0-9_]+")


def _module_constants(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in root.rglob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                out.update({t.id: node.value.value for t in node.targets if isinstance(t, ast.Name)})
    return out


def _as_code(node: ast.AST, constants: Dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
    elif isinstance(node, ast.Name):
        text = constants.get(node.id, "")
    else:
        return None
    return text if CODE_SHAPE.fullmatch(text) else None


def _call_name(call: ast.Call) -> str:
    return getattr(call.func, "id", getattr(call.func, "attr", ""))


def raised_codes(host_dir: Path = HOST_DIR) -> Set[str]:
    constants = _module_constants(host_dir.parent)
    found: Set[str] = set()
    for path in host_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and _call_name(node) in CODE_ARG_INDEX:
                index = CODE_ARG_INDEX[_call_name(node)]
                code = _as_code(node.args[index], constants) if len(node.args) > index else None
            elif isinstance(node, ast.Dict) and {getattr(k, "value", None) for k in node.keys} >= {"code", "detail"}:
                code = _as_code(node.values[[getattr(k, "value", None) for k in node.keys].index("code")], constants)
            else:
                continue
            if code:
                found.add(code)
    return found
