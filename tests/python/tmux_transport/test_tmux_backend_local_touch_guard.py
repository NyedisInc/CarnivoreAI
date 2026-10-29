
from __future__ import annotations

import ast
import inspect
import os
import textwrap
from typing import Callable, Dict, Iterable, List, Optional, Set, Type

from src.core.tmux_backend import TmuxBackend

LOCAL_OS_MEMBERS = frozenset({
    "kill", "killpg", "open", "read", "write", "close", "stat", "fstat", "lseek", "unlink", "remove",
    "rename", "replace", "getpid", "listdir", "scandir", "truncate", "ftruncate", "mkfifo", "makedirs",
    "mkdir", "system", "popen", "waitpid", "execv", "execvp", "fork",
})
LOCAL_MODULES = frozenset({"subprocess", "shutil", "psutil"})
LOCAL_ASYNCIO_MEMBERS = frozenset({"create_subprocess_exec", "create_subprocess_shell", "subprocess"})
LOCAL_PATH_METHODS = frozenset({
    "read_bytes", "read_text", "write_bytes", "write_text", "unlink", "stat", "exists", "mkdir",
    "is_file", "touch", "rmdir", "iterdir", "open", "rename", "replace",
})
LOCAL_PROCESS_TOOLS = frozenset({"ps", "lsof", "kill", "pgrep", "pkill"})

LOCAL_BY_DESIGN: Dict[str, str] = {
    "_tail_once": "follows the local mirror file the remote stream fills",
    "_drain_to_eof": "drains the local mirror file",
    "_maybe_rotate": "rotates the local mirror file",
    "_record_tail_start_offset": "stats the local mirror file",
    "attach_existing": "its dead-pane fallback creates the local mirror, the file the tail loop reads; "
                       "every far-side step goes through the overridden _run_tmux and pipe-file hooks",
}


def _dotted(node: ast.AST) -> Optional[str]:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _call_touches_local(call: ast.Call) -> Optional[str]:
    name = _dotted(call.func)
    if name is None:
        return None
    head, _, rest = name.partition(".")
    last = name.rsplit(".", 1)[-1]
    if name == "open":
        return "open"
    if head in LOCAL_MODULES:
        return name
    if head == "os" and rest.split(".")[0] in LOCAL_OS_MEMBERS:
        return name
    if head == "asyncio" and rest.split(".")[0] in LOCAL_ASYNCIO_MEMBERS:
        return name
    if isinstance(call.func, ast.Attribute) and head not in ("os", "asyncio") and last in LOCAL_PATH_METHODS \
            and not name.startswith("self._host"):
        return name
    return None


def _constant_touches_local(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in LOCAL_PROCESS_TOOLS:
        return f"'{node.value}'"
    return None


def local_touches(func: Callable[..., object]) -> List[str]:
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return []
    found: Set[str] = set()
    for node in ast.walk(tree):
        hit = _call_touches_local(node) if isinstance(node, ast.Call) else _constant_touches_local(node)
        if hit:
            found.add(hit)
    return sorted(found)


def _methods(cls: Type[object]) -> Dict[str, Callable[..., object]]:
    resolved: Dict[str, Callable[..., object]] = {}
    for name in dir(cls):
        value = inspect.getattr_static(cls, name)
        if isinstance(value, (staticmethod, classmethod)):
            value = value.__func__
        elif isinstance(value, property):
            value = value.fget
        if inspect.isfunction(value):
            resolved[name] = value
    return resolved


def unguarded_methods(backend: Type[object], by_design: Iterable[str]) -> Dict[str, List[str]]:
    allowed = set(by_design)
    bad: Dict[str, List[str]] = {}
    for name, func in _methods(backend).items():
        touches = local_touches(func)
        if touches and name not in allowed:
            bad[name] = touches
    return bad


def test_every_local_touching_backend_method_is_named() -> None:
    assert unguarded_methods(TmuxBackend, LOCAL_BY_DESIGN) == {}


def test_every_by_design_entry_still_touches_the_machine() -> None:
    base_methods = _methods(TmuxBackend)
    for name, reason in LOCAL_BY_DESIGN.items():
        assert reason, name
        assert name in base_methods, f"{name} no longer exists on TmuxBackend"
        assert local_touches(base_methods[name]), f"{name} no longer touches this machine"


def test_the_guard_goes_red_on_a_new_method_that_kills_a_pid() -> None:

    class Local(TmuxBackend):
        def reap(self, pid: int) -> None:
            os.kill(pid, 9)

    assert unguarded_methods(Local, LOCAL_BY_DESIGN) == {"reap": ["os.kill"]}


def test_the_guard_goes_red_on_ps_lsof_and_subprocess_spellings() -> None:

    class Local(TmuxBackend):
        def a(self) -> list:
            return ["ps", "-p", "1"]

        def b(self) -> None:
            import subprocess
            subprocess.run(["true"])

        def c(self) -> bytes:
            return self._pipe_path.read_bytes()

    assert set(unguarded_methods(Local, LOCAL_BY_DESIGN)) == {"a", "b", "c"}


def test_naming_a_method_clears_the_flag() -> None:

    class Local(TmuxBackend):
        def reap(self, pid: int) -> None:
            os.kill(pid, 9)

    assert unguarded_methods(Local, {**LOCAL_BY_DESIGN, "reap": "test"}) == {}
