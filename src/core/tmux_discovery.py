
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

from src.core.tmux_control.tmux_error import TmuxError
from src.core.tmux_stderr import listing_env, looks_like_no_server

logger = structlog.get_logger()

TMUX_AVAILABLE = "available"

TMUX_ABSENT = "absent"

TMUX_UNDETERMINED = "undetermined"

WELL_KNOWN_PATHS: Tuple[str, ...] = (
    "/opt/homebrew/bin/tmux",
    "/usr/local/bin/tmux",
    "/opt/local/bin/tmux",
    "/usr/bin/tmux",
    "/bin/tmux",
)

PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class TmuxProbe:

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
    _stable_choice.clear()
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

SELECTION_STABLE_MAX_SECONDS = 300.0

_selection_cache: Dict[str, Tuple[float, Optional[str], Optional["TmuxVersionSkewError"]]] = {}

_stable_choice: Dict[str, Tuple[Tuple[int, int, int], float]] = {}

_binary_versions: Dict[str, Optional[str]] = {}


class TmuxVersionSkewError(TmuxError):

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


def socket_signature(socket_name: str) -> Optional[Tuple[int, int, int]]:
    base = os.environ.get("TMUX_TMPDIR") or "/tmp"
    try:
        stat = os.stat(os.path.join(base, "tmux-%d" % os.getuid(), socket_name))
    except OSError:
        return None
    return (stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns)


def _select(socket_name: str) -> Tuple[Optional[str], bool]:
    candidates = candidate_tmux_paths()
    if not candidates:
        return None, False
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
        return default, False
    for path in candidates:
        if versions_match(binary_version(path), srv):
            return path, True
    raise TmuxVersionSkewError(socket_name, srv, default, binary_version(default),
                               tuple((p, binary_version(p)) for p in candidates))


def _still_same_server(socket_name: str, now: float) -> bool:
    known = _stable_choice.get(socket_name)
    if known is None or now - known[1] >= SELECTION_STABLE_MAX_SECONDS:
        return False
    return socket_signature(socket_name) == known[0]


def select_tmux(socket_name: str) -> Optional[str]:
    now = time.monotonic()
    hit = _selection_cache.get(socket_name)
    if hit is not None and hit[0] <= now and hit[2] is None and _still_same_server(socket_name, now):
        hit = (now + SELECTION_TTL_SECONDS, hit[1], None)
        _selection_cache[socket_name] = hit
    if hit is None or hit[0] <= now:
        try:
            chosen, answered = _select(socket_name)
            signature = socket_signature(socket_name) if answered else None
            if signature is not None:
                _stable_choice[socket_name] = (signature, now)
            else:
                _stable_choice.pop(socket_name, None)
            hit = (now + SELECTION_TTL_SECONDS, chosen, None)
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
