
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

from scripts.perf.tmux_socket_file import (
    PERF_SOCKET_PREFIX,
    kill_server_and_unlink,
    tmux_socket_dir,
)
from tests import tmux_start_retry

__all__ = [
    "TEST_SOCKET_PREFIX",
    "TEST_SOCKET_NAME",
    "FORBIDDEN_SOCKET_NAME",
    "FORBIDDEN_SOCKET_NAMES",
    "TmuxSocketGuardError",
    "classify_tmux_argv",
    "assert_safe_socket_name",
    "install_subprocess_guard",
    "remove_subprocess_guard",
    "guard_is_installed",
    "install_default_socket_redirect",
    "remove_default_socket_redirect",
    "default_redirect_is_installed",
    "shipped_default_socket_name",
    "auth_config_redirect_state",
    "derive_test_socket",
    "kill_test_socket_server",
    "sweep_stale_test_sockets",
]


TEST_SOCKET_PREFIX: str = "cloude_pytest_"

FORBIDDEN_SOCKET_NAME: str = "cloude"

def _forbidden_socket_names() -> Tuple[str, ...]:
    try:
        from src.core.product_identity import (
            LEGACY_TMUX_SOCKET_NAMES,
            TMUX_SOCKET_NAME,
        )
    except ImportError:
        return (FORBIDDEN_SOCKET_NAME,)
    names = (TMUX_SOCKET_NAME, *LEGACY_TMUX_SOCKET_NAMES, FORBIDDEN_SOCKET_NAME)
    seen: List[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return tuple(seen)


FORBIDDEN_SOCKET_NAMES: Tuple[str, ...] = _forbidden_socket_names()

TEST_SOCKET_NAME: str = f"{TEST_SOCKET_PREFIX}{os.getpid()}_{uuid.uuid4().hex[:8]}"


class TmuxSocketGuardError(RuntimeError):
    pass


def _as_argv_list(cmd: Any) -> Optional[List[str]]:
    if isinstance(cmd, (str, bytes, Path)):
        return None
    if isinstance(cmd, Sequence):
        out: List[str] = []
        for part in cmd:
            if isinstance(part, bytes):
                out.append(part.decode("utf-8", "replace"))
            else:
                out.append(str(part))
        return out
    return None


def _looks_like_tmux(token: str) -> bool:
    return os.path.basename(token) == "tmux"


def _mentions_tmux_command(token: str) -> bool:
    for sep in (";", "|", "&", "(", ")", "\n"):
        token = token.replace(sep, " ")
    return any(_looks_like_tmux(part) for part in token.split() if part)


def classify_tmux_argv(cmd: Any) -> Tuple[str, Optional[str], str]:
    argv = _as_argv_list(cmd)

    if argv is None:
        text = cmd.decode("utf-8", "replace") if isinstance(cmd, bytes) else str(cmd)
        if "tmux" in text:
            return (
                "undetermined",
                None,
                "tmux invoked through an unparseable shell string; the target "
                f"socket cannot be determined: {text!r}",
            )
        return ("not_tmux", None, "not a tmux invocation")

    if not argv:
        return ("not_tmux", None, "empty argv")

    if not _looks_like_tmux(argv[0]):
        if any(_mentions_tmux_command(tok) for tok in argv):
            return (
                "undetermined",
                None,
                "tmux appears in argv but not as argv[0], so the socket flag "
                f"cannot be attributed reliably: {argv!r}",
            )
        return ("not_tmux", None, "not a tmux invocation")

    if len(argv) == 2 and argv[1] in ("-V", "-h"):
        return (
            "safe",
            None,
            f"tmux {argv[1]} answers from the binary and opens no socket",
        )

    for i, tok in enumerate(argv[1:], start=1):
        if tok == "-L":
            if i + 1 >= len(argv):
                return (
                    "undetermined",
                    None,
                    f"tmux -L given with no socket name: {argv!r}",
                )
            return _verdict_for_name(argv[i + 1], argv)
        if tok.startswith("-L") and len(tok) > 2:
            return _verdict_for_name(tok[2:], argv)
        if tok == "-S":
            if i + 1 >= len(argv):
                return (
                    "undetermined",
                    None,
                    f"tmux -S given with no socket path: {argv!r}",
                )
            return _verdict_for_name(os.path.basename(argv[i + 1]), argv)
        if tok.startswith("-S") and len(tok) > 2:
            return _verdict_for_name(os.path.basename(tok[2:]), argv)

    return (
        "unsafe",
        "default",
        "tmux invoked with no -L/-S, which targets the shared default "
        f"socket rather than the test socket: {argv!r}",
    )


def _verdict_for_name(name: str, argv: List[str]) -> Tuple[str, Optional[str], str]:
    if not name:
        return ("undetermined", None, f"empty socket name in: {argv!r}")
    if name == TEST_SOCKET_NAME or name.startswith(TEST_SOCKET_NAME + "_"):
        return ("safe", name, "targets this run's test socket")
    if name == FORBIDDEN_SOCKET_NAME:
        return (
            "unsafe",
            name,
            f"targets the PRODUCTION socket {FORBIDDEN_SOCKET_NAME!r}: {argv!r}",
        )
    return (
        "unsafe",
        name,
        f"targets socket {name!r}, which is not this run's test socket "
        f"{TEST_SOCKET_NAME!r}: {argv!r}",
    )


def assert_safe_socket_name(name: Optional[str], context: str) -> None:
    if name is None:
        raise TmuxSocketGuardError(
            f"{context}: socket name could not be determined. Under the "
            "three-outcome rule this is a failure, not a pass."
        )
    if name != TEST_SOCKET_NAME:
        raise TmuxSocketGuardError(
            f"{context}: resolved socket {name!r} is not this run's test "
            f"socket {TEST_SOCKET_NAME!r}."
        )


_DERIVED_SOCKETS: set = set()


def derive_test_socket(label: str) -> str:
    name = f"{TEST_SOCKET_NAME}_{label}_{uuid.uuid4().hex[:8]}"
    _DERIVED_SOCKETS.add(name)
    return name



_ORIGINALS: dict = {}


def _guarded(original: Callable, label: str) -> Callable:

    def wrapper(*args, **kwargs):
        if args:
            cmd: Any = args[0]
        elif "args" in kwargs:
            cmd = kwargs["args"]
        elif "program" in kwargs:
            cmd = [kwargs["program"], *args[1:]]
        else:
            cmd = None

        if label == "asyncio.create_subprocess_exec" and args:
            cmd = list(args)

        verdict = "not_tmux"
        if cmd is not None:
            verdict, name, detail = classify_tmux_argv(cmd)
            if verdict == "unsafe":
                raise TmuxSocketGuardError(
                    f"BLOCKED tmux invocation via {label}: {detail} "
                    f"Tests must use tests.socket_guard.TEST_SOCKET_NAME."
                )
            if verdict == "undetermined":
                raise TmuxSocketGuardError(
                    f"BLOCKED tmux invocation via {label}: {detail} "
                    "The target socket could not be determined, which the "
                    "three-outcome rule treats as a failure, not a pass."
                )

        if (
            verdict == "safe"
            and label in tmux_start_retry.RETRYABLE_SUBPROCESS_LABELS
            and tmux_start_retry.is_tmux_start_argv(_as_argv_list(cmd) or [])
        ):
            return tmux_start_retry.run_tmux_start_with_retry(original, args, kwargs)
        return original(*args, **kwargs)

    wrapper.__name__ = getattr(original, "__name__", "guarded")
    wrapper.__doc__ = f"Socket-guarded wrapper around {label}."
    return wrapper


def install_subprocess_guard() -> None:
    if _ORIGINALS:
        return

    import asyncio

    targets = [
        (subprocess, "run", "subprocess.run"),
        (subprocess, "Popen", "subprocess.Popen"),
        (subprocess, "call", "subprocess.call"),
        (subprocess, "check_call", "subprocess.check_call"),
        (subprocess, "check_output", "subprocess.check_output"),
        (asyncio, "create_subprocess_exec", "asyncio.create_subprocess_exec"),
        (asyncio, "create_subprocess_shell", "asyncio.create_subprocess_shell"),
    ]
    for module, attr, label in targets:
        original = getattr(module, attr, None)
        if original is None:
            continue
        _ORIGINALS[(module.__name__, attr)] = (module, attr, original)
        setattr(module, attr, _guarded(original, label))


def remove_subprocess_guard() -> None:
    for module, attr, original in list(_ORIGINALS.values()):
        setattr(module, attr, original)
    _ORIGINALS.clear()


def guard_is_installed() -> bool:
    return bool(_ORIGINALS)



_DEFAULT_PATCHES: List[Tuple[Any, str, Any]] = []
_FUNC_DEFAULT_PATCHES: List[Tuple[Any, tuple]] = []
_KWDEFAULT_PATCHES: List[Tuple[Any, dict]] = []


def install_default_socket_redirect() -> None:
    import inspect
    import sys

    if _DEFAULT_PATCHES or _FUNC_DEFAULT_PATCHES:
        return

    import src.core.tmux_backend  # noqa: F401

    for mod_name, module in list(sys.modules.items()):
        if not (mod_name == "src" or mod_name.startswith("src.")):
            continue
        if module is None:
            continue

        current = getattr(module, "DEFAULT_SOCKET_NAME", None)
        if current in FORBIDDEN_SOCKET_NAMES:
            _DEFAULT_PATCHES.append((module, "DEFAULT_SOCKET_NAME", current))
            setattr(module, "DEFAULT_SOCKET_NAME", TEST_SOCKET_NAME)

        holders = [module] + [
            obj for obj in vars(module).values() if isinstance(obj, type)
        ]
        for holder in holders:
            for obj in list(vars(holder).values()):
                func = obj
                if isinstance(obj, (classmethod, staticmethod)):
                    func = obj.__func__
                if not inspect.isfunction(func):
                    continue

                defaults = func.__defaults__
                if defaults and any(v in FORBIDDEN_SOCKET_NAMES for v in defaults):
                    _FUNC_DEFAULT_PATCHES.append((func, defaults))
                    func.__defaults__ = tuple(
                        TEST_SOCKET_NAME if v in FORBIDDEN_SOCKET_NAMES else v
                        for v in defaults
                    )

                kwdefaults = func.__kwdefaults__
                if kwdefaults and any(
                    v in FORBIDDEN_SOCKET_NAMES for v in kwdefaults.values()
                ):
                    _KWDEFAULT_PATCHES.append((func, dict(kwdefaults)))
                    func.__kwdefaults__ = {
                        k: (TEST_SOCKET_NAME if v in FORBIDDEN_SOCKET_NAMES else v)
                        for k, v in kwdefaults.items()
                    }

    _install_ladder_config_redirect()
    _install_auth_config_redirect()


def _install_ladder_config_redirect() -> None:
    try:
        from src.core import tmux_socket_resolution
    except ImportError:
        return

    if getattr(tmux_socket_resolution.configured_tmux_socket_name, "__wrapped_by_socket_guard__", False):
        return

    original = tmux_socket_resolution.configured_tmux_socket_name

    def patched(settings_obj):
        result = original(settings_obj)
        if result is None or result in FORBIDDEN_SOCKET_NAMES:
            return TEST_SOCKET_NAME
        return result

    patched.__name__ = "configured_tmux_socket_name"
    patched.__doc__ = "Socket-guarded wrapper around configured_tmux_socket_name."
    patched.__wrapped_by_socket_guard__ = True
    _DEFAULT_PATCHES.append(
        (tmux_socket_resolution, "configured_tmux_socket_name", original)
    )
    tmux_socket_resolution.configured_tmux_socket_name = patched


_AUTH_REDIRECT_STATE: dict = {"reason": "not attempted"}


def auth_config_redirect_state() -> str:
    return _AUTH_REDIRECT_STATE["reason"]


def _install_auth_config_redirect() -> None:
    try:
        from src import config as config_module
    except (ImportError, SystemExit, ValueError):
        _AUTH_REDIRECT_STATE["reason"] = "src.config could not be imported"
        return

    original = config_module.Settings.load_auth_config

    def patched(self, *args, **kwargs):
        auth_config = original(self, *args, **kwargs)
        session = getattr(auth_config, "session", None)
        if session is not None:
            if getattr(session, "tmux_socket_name", None) in FORBIDDEN_SOCKET_NAMES:
                try:
                    session.tmux_socket_name = TEST_SOCKET_NAME
                except (AttributeError, TypeError, ValueError):
                    raise TmuxSocketGuardError(
                        "auth config carries the production socket name and "
                        "it could not be redirected to the test socket"
                    )
        return auth_config

    patched.__name__ = "load_auth_config"
    patched.__doc__ = "Socket-guarded wrapper around Settings.load_auth_config."
    _DEFAULT_PATCHES.append(
        (config_module.Settings, "load_auth_config", original)
    )
    config_module.Settings.load_auth_config = patched
    _AUTH_REDIRECT_STATE["reason"] = "installed"


def remove_default_socket_redirect() -> None:
    for module, attr, original in _DEFAULT_PATCHES:
        setattr(module, attr, original)
    _DEFAULT_PATCHES.clear()
    for func, defaults in _FUNC_DEFAULT_PATCHES:
        func.__defaults__ = defaults
    _FUNC_DEFAULT_PATCHES.clear()
    for func, kwdefaults in _KWDEFAULT_PATCHES:
        func.__kwdefaults__ = kwdefaults
    _KWDEFAULT_PATCHES.clear()


def default_redirect_is_installed() -> bool:
    return bool(_DEFAULT_PATCHES or _FUNC_DEFAULT_PATCHES)


def shipped_default_socket_name() -> str:
    import ast

    source_path = (
        Path(__file__).resolve().parent.parent / "src" / "core" / "tmux_backend.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        else:
            continue
        if "DEFAULT_SOCKET_NAME" not in targets:
            continue
        if isinstance(value, ast.Constant):
            return str(value.value)
        if isinstance(value, ast.Name):
            return _shipped_product_identity_constant(value.id)
    raise AssertionError(
        f"DEFAULT_SOCKET_NAME not found as a module-level constant in {source_path}"
    )


def _shipped_product_identity_constant(name: str) -> str:
    import ast

    source_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "core"
        / "product_identity.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        else:
            continue
        if name in targets and isinstance(value, ast.Constant):
            return str(value.value)
    raise AssertionError(
        f"{name!r} not found as a module-level constant in {source_path}"
    )


def kill_test_socket_server() -> None:
    original = _ORIGINALS.get(("subprocess", "run"))
    run = original[2] if original else subprocess.run
    for name in [TEST_SOCKET_NAME, *sorted(_DERIVED_SOCKETS)]:
        kill_server_and_unlink(name, run=run)


_SWEEP_PREFIXES: Tuple[str, ...] = (TEST_SOCKET_PREFIX, PERF_SOCKET_PREFIX)
_SWEEP_DEAD_MIN_AGE_S: float = 3600.0
_SWEEP_LIVE_MIN_AGE_S: float = 12 * 3600.0
_SWEEP_MAX_ENTRIES: int = 100_000
_SWEEP_MAX_TMUX_PROBES: int = 200


def _socket_answers(path: str) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1.0)
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


def sweep_stale_test_sockets(now: Optional[float] = None) -> Tuple[int, int]:
    now = time.time() if now is None else now
    original = _ORIGINALS.get(("subprocess", "run"))
    run = original[2] if original else subprocess.run
    removed = killed = probes = 0
    try:
        with os.scandir(tmux_socket_dir()) as entries:
            for count, entry in enumerate(entries):
                if count >= _SWEEP_MAX_ENTRIES:
                    break
                name = entry.name
                if not name.startswith(_SWEEP_PREFIXES) or name in (
                    *FORBIDDEN_SOCKET_NAMES, "default"
                ):
                    continue
                try:
                    age = now - entry.stat(follow_symlinks=False).st_mtime
                    if age < _SWEEP_DEAD_MIN_AGE_S:
                        continue
                    if not _socket_answers(entry.path):
                        os.unlink(entry.path)
                        removed += 1
                        continue
                    if probes >= _SWEEP_MAX_TMUX_PROBES:
                        continue
                    probes += 1
                    listing = run(
                        ["tmux", "-L", name, "list-sessions", "-F",
                         "#{start_time} #{session_attached}"],
                        capture_output=True, text=True, timeout=5,
                    )
                    rows = [line.split() for line in listing.stdout.splitlines() if line]
                    if listing.returncode != 0 or not rows:
                        continue
                    started = min(int(row[0]) for row in rows)
                    attached = sum(int(row[1]) for row in rows)
                    if attached == 0 and now - started > _SWEEP_LIVE_MIN_AGE_S:
                        kill_server_and_unlink(name, run=run)
                        killed += 1
                except FileNotFoundError:
                    continue
                except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
                    sys.stderr.write(f"tmux socket sweep skipped {name}: {exc!r}\n")
    except FileNotFoundError:
        pass
    except OSError as exc:
        sys.stderr.write(f"tmux socket sweep stopped: {exc!r}\n")
    return (removed, killed)
