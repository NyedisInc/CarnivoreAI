
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Set, Tuple

SRC = Path(__file__).resolve().parents[3] / "src"

STORE_NAMES = ("state.json", "installs.json", "sideload.json", "third-party.json", "STATE_FILE", "LEDGER_FILE", "SIDELOAD_FILE", "THIRD_PARTY_FILE")
STORE_HELPERS = ("state_path", "_ledger_path", "switch_path", "legacy_path")
WRITE_NAMES = {"atomic_write_json", "atomic_write_text", "open"}
WRITE_ATTRS = {("os", "replace"), ("os", "rename"), ("shutil", "move"), ("json", "dump")}
WRITE_METHODS = {"write_text", "write_bytes"}

BOUNDARY = {"src/plugins/host/registry_store.py", "src/plugins/host/registry_files.py"}

ALLOWED: dict = {
    ("src/plugins/host/legacy_move.py", "_copy_json"): "one-time addons/ to cplugs/ folder move: it rewrites state.json inside a temp copy "
    "that is published whole by os.replace, before the host, the runtime or plugins.json exist",
}


def _functions(tree: ast.AST) -> Iterator[ast.AST]:
    return (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _is_write(call: ast.Call) -> bool:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id in WRITE_NAMES
    if isinstance(target, ast.Attribute):
        base = target.value.id if isinstance(target.value, ast.Name) else ""
        return (base, target.attr) in WRITE_ATTRS or target.attr in WRITE_METHODS
    return False


def _function_text_names(fn: ast.AST) -> Tuple[Set[str], Set[str]]:
    docstring = fn.body[0].value if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) else None
    strings = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not docstring}
    own = {"owner_state", "registry_store", "identity", "sideload", "state"}
    idents = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    idents |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in own}
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    called |= {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id in own}
    return strings, (idents & set(STORE_NAMES[4:])) | (called & set(STORE_HELPERS))


def offenders(root: Path = SRC) -> List[str]:
    found: List[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        if rel in BOUNDARY:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in _functions(tree):
            writes = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and _is_write(c)]
            if not writes or (rel, fn.name) in ALLOWED:
                continue
            strings, idents = _function_text_names(fn)
            names_store = any(s == n or s.endswith("/" + n) for s in strings for n in STORE_NAMES[:4]) or bool(idents)
            if names_store:
                found.append(f"{rel}:{fn.name}:{writes[0].lineno}")
    return found


def test_only_registry_store_writes_the_four_plugin_stores():
    bad = offenders()
    assert not bad, (
        "these functions write state.json, installs.json, sideload.json or third-party.json outside src/plugins/host/registry_store.py and registry_files.py (its file-level half, called only under the lock):\n  "
        + "\n  ".join(bad) + "\n\nEvery write goes through registry_store.write_document (inside registry_store.exclusive) or registry_store.commit, "
        "or a second writer loses an update and plugins.json drifts from the files it projects."
    )


def test_the_scan_goes_red_on_a_writer_outside_the_boundary(tmp_path):
    pkg = tmp_path / "src"
    pkg.mkdir()
    (pkg / "rogue.py").write_text("def save(d, data):\n    atomic_write_json(d / 'cplugs' / 'state.json', data)\n")
    (pkg / "fine.py").write_text("def save(d, data):\n    atomic_write_json(d / 'other.json', data)\n")
    (pkg / "helper.py").write_text("def save(d, data):\n    os.replace(tmp, state_path(d))\n")
    assert sorted(offenders(pkg)) == ["src/helper.py:save:2", "src/rogue.py:save:2"]


def test_the_boundary_still_carries_the_write_sequence():
    store = (SRC / "plugins" / "host" / "registry_store.py").read_text(encoding="utf-8")
    source = (SRC / "plugins" / "host" / "registry_files.py").read_text(encoding="utf-8")
    source = source[source.index("def write_registry("):]
    backup, temp = source.index('".bak"'), source.index("unique_tmp_path(path)")
    fsync, replace = source.index("os.fsync(handle.fileno())", temp), source.index("os.replace(temp, path)")
    assert backup < temp < fsync < replace
    assert "fcntl.flock(fd, fcntl.LOCK_EX" in store
