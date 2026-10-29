"""Where tmux is, whether it runs, and how to say "I could not tell".

THE TWO PROBLEMS THIS SOLVES

1. A GUI-LAUNCHED APP HAS NO SHELL PATH. Measured on the development
   machine::

       env -i /usr/bin/which tmux       -> nothing, exit 1
       env -i /bin/sh -c 'echo $PATH'   -> /usr/gnu/bin:/usr/local/bin:/bin:/usr/bin:.
       /opt/homebrew/bin/tmux -V        -> tmux 3.7c

   tmux is installed and runs perfectly; it is simply not on the PATH a
   process inherits when launched from the Finder or launchd. The packaged
   app found it anyway, but only because ``macOS/server-manager.js``
   prepends ``/opt/homebrew/bin:/usr/local/bin`` to PATH before spawning
   the server. That is one launcher's PATH, not discovery: an adopted
   server, a launchd job, or ``start.sh`` run from a GUI context all see
   the bare PATH, find nothing, and silently degrade to the PTY backend.
   So this module searches PATH *and* the places tmux is actually
   installed, which works regardless of how the process was started.

2. ``shutil.which`` IS NOT PROOF THE BINARY RUNS. which() reports that a
   name resolves to a file with the executable bit set. A quarantined
   binary, a wrong-architecture build, a broken dylib link and a dangling
   symlink all resolve and all fail to execute. The session-backend factory
   used to go straight from ``bool(shutil.which("tmux"))`` to logging
   ``session_backend_selected backend=tmux`` - a verdict about executability
   that nothing had measured.

THREE OUTCOMES, per this repo's standard, and the third is not a flavour of
the other two:

    AVAILABLE     - a path resolved AND running it returned a version.
    ABSENT        - nothing resolved anywhere. tmux is not installed.
    UNDETERMINED  - something resolved and could not be run (non-zero exit,
                    timeout, OSError). This is NOT "tmux is missing" and it
                    is emphatically NOT "tmux is available". The caller must
                    refuse to claim the tmux backend and must say why.

The probe executes a subprocess, so it is memoized for the process lifetime -
session creation is a hot path and must not fork a tmux per attempt. Call
:func:`reset_probe_cache` in tests.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.tmux_stderr import listing_env, looks_like_no_server

logger = structlog.get_logger()

TMUX_AVAILABLE = "available"

TMUX_ABSENT = "absent"

# could not
TMUX_UNDETERMINED = "undetermined"

WELL_KNOWN_PATHS: Tuple[str, ...] = (
    "/opt/homebrew/bin/tmux",
    "/usr/local/bin/tmux",
    "/opt/local/bin/tmux",
    "/usr/bin/tmux",
    "/bin/tmux",
)

# could not
PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class TmuxProbe:
    """The result of asking whether tmux can be run.

    Attributes:
        state: One of :data:`TMUX_AVAILABLE`, :data:`TMUX_ABSENT`,
            :data:`TMUX_UNDETERMINED`.
        path: Absolute path that resolved, or None when nothing did. Present
            even when the state is UNDETERMINED, because knowing WHICH
            binary failed is most of the diagnosis.
        version: The version string tmux reported, or None.
        detail: Human-readable reason, always non-empty. Rendered to the
            user and to logs, so it must say what could not be measured
            rather than leaving a blank.
    """

    state: str
    path: Optional[str]
    version: Optional[str]
    detail: str

    @property
    def usable(self) -> bool:
        return self.state == TMUX_AVAILABLE


_cached: Optional[TmuxProbe] = None


def reset_probe_cache() -> None:
    global _cached
    _cached = None
    _selection_cache.clear()
    _binary_versions.clear()


def resolve_tmux_path() -> Optional[str]:
    found = shutil.which("tmux")
    if found:
        return found
    for candidate in WELL_KNOWN_PATHS:
        p = Path(candidate)
        try:
            if p.is_file():
                return str(p)
        except OSError:
            continue
    return None


def probe_tmux() -> TmuxProbe:
    """Resolve tmux and prove it runs, memoized for the process lifetime.

    Returns:
        A :class:`TmuxProbe`. Never raises: every failure mode is one of
        the three states, because a caller that has to catch an exception
        to learn "I could not tell" will eventually forget to.
    """
    global _cached
    if _cached is not None:
        return _cached

    path = resolve_tmux_path()
    if path is None:
        _cached = TmuxProbe(
            state=TMUX_ABSENT,
            path=None,
            version=None,
            detail=(
                "tmux was not found on PATH or at any of "
                f"{', '.join(WELL_KNOWN_PATHS)}. Install it with: "
                "brew install tmux"
            ),
        )
        logger.warning(
            "tmux_probe", state=TMUX_ABSENT, detail=_cached.detail
        )
        return _cached

    try:
        completed = subprocess.run(
            [path, "-V"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _cached = TmuxProbe(
            state=TMUX_UNDETERMINED,
            path=path,
            version=None,
            detail=(
                f"{path} resolved but `tmux -V` timed out after "
                f"{PROBE_TIMEOUT_SECONDS:g}s, so whether tmux works here "
                "CANNOT BE DETERMINED."
            ),
        )
    except OSError as exc:
        _cached = TmuxProbe(
            state=TMUX_UNDETERMINED,
            path=path,
            version=None,
            detail=(
                f"{path} resolved but could not be executed ({exc}), so "
                "whether tmux works here CANNOT BE DETERMINED."
            ),
        )
    else:
        if completed.returncode == 0:
            version = (completed.stdout or completed.stderr or "").strip() or None
            _cached = TmuxProbe(
                state=TMUX_AVAILABLE,
                path=path,
                version=version,
                detail=f"{path} ran and reported {version or 'no version string'}",
            )
        else:
            stderr = (completed.stderr or completed.stdout or "").strip()
            _cached = TmuxProbe(
                state=TMUX_UNDETERMINED,
                path=path,
                version=None,
                detail=(
                    f"{path} resolved but `tmux -V` exited "
                    f"{completed.returncode}"
                    + (f": {stderr[:200]}" if stderr else "")
                    + ". Whether tmux works here CANNOT BE DETERMINED."
                ),
            )

    log = logger.info if _cached.state == TMUX_AVAILABLE else logger.warning
    log(
        "tmux_probe",
        state=_cached.state,
        path=_cached.path,
        version=_cached.version,
        detail=_cached.detail,
    )
    return _cached



BUNDLED_TMUX_ENV = "CARNIVORE_BUNDLED_TMUX"
STAGE_DIR_ENV = "CARNIVORE_TMUX_STAGE_DIR"
PAYLOAD_ONLY_ENV = ("PYTHONNOUSERSITE", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE", "CARNIVORE_PAYLOAD_PYTHON",
                    BUNDLED_TMUX_ENV, STAGE_DIR_ENV)

SELECTION_TTL_SECONDS = 5.0

_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

_selection_cache: Dict[str, Tuple[float, Optional[str], Optional["TmuxVersionSkewError"]]] = {}

_binary_versions: Dict[str, Optional[str]] = {}


class TmuxVersionSkewError(RuntimeError):

    def __init__(self, socket_name: str, server_version: Optional[str],
                 client_path: Optional[str], client_version: Optional[str],
                 tried: Tuple[Tuple[str, Optional[str]], ...]) -> None:
        self.socket_name = socket_name
        self.server_version = server_version
        self.client_path = client_path
        self.client_version = client_version
        self.tried = tried
        super().__init__(
            f"tmux version skew on socket {socket_name!r}: the running server is "
            f"{server_version or 'a version this client cannot talk to'}, the tmux client "
            f"{client_path or '?'} is {client_version or 'unknown'}, and none of "
            f"{', '.join(f'{p} ({v or 'unknown'})' for p, v in tried) or 'no binaries'} matches the server"
        )


def tmux_version_key(text: Optional[str]) -> Optional[Tuple[int, int]]:
    m = _VERSION_RE.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def versions_match(client: Optional[str], server: Optional[str]) -> bool:
    a, b = tmux_version_key(client), tmux_version_key(server)
    if a is not None or b is not None:
        return a == b
    return bool(client) and (client or "").strip().removeprefix("tmux ") == (server or "").strip().removeprefix("tmux ")


def _staged_copy_matches_key(path: str) -> bool:
    key = os.path.basename(os.path.dirname(path))
    if not re.fullmatch(r"[0-9a-f]{16}", key):
        return False
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:16] == key
    except OSError:
        return False


def _staged_tmux_paths() -> List[str]:
    stage = os.environ.get(STAGE_DIR_ENV)
    if not stage:
        return []
    try:
        found = [p for p in (os.path.join(stage, name, "tmux") for name in os.listdir(stage)) if _staged_copy_matches_key(p)]
        return sorted(found, key=lambda p: os.stat(p).st_mtime if os.path.exists(p) else 0.0, reverse=True)
    except OSError:
        return []


def pane_client_env() -> Dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in PAYLOAD_ONLY_ENV}


def candidate_tmux_paths() -> List[str]:
    raw = [os.environ.get(BUNDLED_TMUX_ENV), *_staged_tmux_paths(), resolve_tmux_path(), *WELL_KNOWN_PATHS]
    seen: set = set()
    out: List[str] = []
    for path in raw:
        try:
            if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
                continue
            real = os.path.realpath(path)
        except OSError:
            continue
        if real not in seen:
            seen.add(real)
            out.append(path)
    return out


def _run_text(argv: List[str]) -> Optional[Tuple[int, str, str]]:
    """Run a short tmux query; None when it could not run or timed out."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
                              env=listing_env(), check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("tmux_version_probe_failed", argv=argv, error=str(exc))
        return None
    return done.returncode, done.stdout or "", done.stderr or ""


def binary_version(path: str) -> Optional[str]:
    if path not in _binary_versions:
        got = _run_text([path, "-V"])
        text = got[1].strip().removeprefix("tmux ").strip() if got and got[0] == 0 else ""
        _binary_versions[path] = text or None
    return _binary_versions[path]


def server_version(path: str, socket_name: str) -> Tuple[str, Optional[str]]:
    got = _run_text([path, "-L", socket_name, "display-message", "-p", "#{version}"])
    if got is None:
        return "unknown", None
    rc, out, err = got
    if rc == 0 and out.strip():
        return "answered", out.strip()
    if "protocol version mismatch" in err:
        return "mismatch", None
    if looks_like_no_server(err):
        return "no_server", None
    return "unknown", None


def _select(socket_name: str) -> Optional[str]:
    candidates = candidate_tmux_paths()
    if not candidates:
        return None
    default = candidates[0]
    state, srv = "unknown", None
    for path in candidates:
        state, srv = server_version(path, socket_name)
        if state in ("answered", "no_server"):
            break
    if state != "answered":
        if state == "mismatch":
            raise TmuxVersionSkewError(socket_name, None, default, binary_version(default),
                                       tuple((p, binary_version(p)) for p in candidates))
        return default
    for path in candidates:
        if versions_match(binary_version(path), srv):
            return path
    raise TmuxVersionSkewError(socket_name, srv, default, binary_version(default),
                               tuple((p, binary_version(p)) for p in candidates))


def select_tmux(socket_name: str) -> Optional[str]:
    now = time.monotonic()
    hit = _selection_cache.get(socket_name)
    if hit is None or hit[0] <= now:
        try:
            hit = (now + SELECTION_TTL_SECONDS, _select(socket_name), None)
        except TmuxVersionSkewError as exc:
            logger.error("tmux_version_skew", socket=socket_name, server=exc.server_version,
                         client=exc.client_version)
            hit = (now + SELECTION_TTL_SECONDS, None, exc)
        _selection_cache[socket_name] = hit
    if hit[2] is not None:
        raise hit[2]
    return hit[1]


def tmux_argv_prefix(socket_name: str) -> list[str]:
    return [select_tmux(socket_name) or "tmux", "-L", socket_name]
