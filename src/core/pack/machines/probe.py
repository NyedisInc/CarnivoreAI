
from __future__ import annotations

import json
import os
import platform
import plistlib
import subprocess
import threading
import time
from pathlib import Path
from xml.parsers.expat import ExpatError
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.pack.errors.input_error import PackInputError
from src.core.dev_tools import git_guard
from src.core.pack.machines import can_block

log = structlog.get_logger(__name__)

TOOL_NAMES = can_block.TOOL_NAMES
EXTRA_DIRS: Tuple[str, ...] = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin")
VERSION_MANAGER_DIRS: Tuple[str, ...] = ("~/.nvm/versions/node/*/bin", "~/.volta/bin", "~/.asdf/shims", "~/.pyenv/shims", "~/.cargo/bin",
                                         "~/.bun/bin", "~/.npm-global/bin", "~/bin")
MAX_MANAGER_DIRS = 64
XCODE_SELECT_ARGV: List[str] = ["/usr/bin/xcode-select", "-p"]
SYSTEM_PROFILER_ARGV: List[str] = ["/usr/sbin/system_profiler", "SPDisplaysDataType", "-json"]
_NVIDIA_FLAGS = ["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
NVIDIA_SMI_ARGVS: Tuple[Tuple[str, ...], ...] = tuple(
    (path, *_NVIDIA_FLAGS) for path in ("/usr/bin/nvidia-smi", "/usr/local/bin/nvidia-smi", "C:\\Windows\\System32\\nvidia-smi.exe"))
FIXED_ARGV: Tuple[Tuple[str, ...], ...] = (tuple(XCODE_SELECT_ARGV), tuple(SYSTEM_PROFILER_ARGV), *NVIDIA_SMI_ARGVS)
COMMAND_TIMEOUT_S = 5.0
PROFILER_TIMEOUT_S = 10.0
PROBE_BUDGET_S = 30.0
DUE_AFTER_S = 24 * 3600.0
MIN_GAP_S = 60.0
MAX_GPUS = 4
BREW_PATHS: Tuple[str, ...] = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
_SIM_ROOT = Path("/Library/Developer/CoreSimulator")
_CLT_MARK = "CommandLineTools"
_VENDORS = {"apple": "apple", "nvidia": "nvidia", "amd": "amd", "ati": "amd", "intel": "intel"}
_OS_FAMILY = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}


def _timeout_for(argv: List[str]) -> float:
    return PROFILER_TIMEOUT_S if argv and os.path.basename(argv[0]) == "system_profiler" else COMMAND_TIMEOUT_S


def _run(argv: List[str]) -> Optional[str]:
    timeout = _timeout_for(argv)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("pack_probe_command_failed", command=os.path.basename(argv[0]), error=type(exc).__name__)
        return None
    return done.stdout if done.returncode == 0 else None


def _expand(extra_dirs: Sequence[str], home: Path) -> List[str]:
    return [str(home / d[2:]) if d.startswith("~/") else d for d in extra_dirs]


def version_manager_dirs(home: Path) -> List[str]:
    found: List[str] = []
    for pattern in VERSION_MANAGER_DIRS:
        try:
            found += sorted(str(p) for p in home.glob(pattern[2:]) if p.is_dir())
        except OSError:
            continue
    return found[:MAX_MANAGER_DIRS]


def find_tools(extra_dirs: Sequence[str], *, system: str = "", apps_dir: Path = Path("/Applications"),
               home: Optional[Path] = None) -> Dict[str, bool]:
    dirs = [*extra_dirs, *(version_manager_dirs(home) if home is not None else [])]
    found = {name: git_guard.tool_available(name, extra_dirs=dirs) for name in TOOL_NAMES}
    if (system or platform.system()) == "Darwin" and not found["blender"]:
        found["blender"] = (apps_dir / "Blender.app").is_dir()
    return found


def tool_present(name: str, *, home: Optional[Path] = None) -> bool:
    base = home or Path.home()
    return git_guard.tool_available(name, extra_dirs=[*_expand(EXTRA_DIRS, base), *version_manager_dirs(base)])


def brew_path() -> Optional[str]:
    for candidate in BREW_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _has_simruntime(root: Path) -> bool:
    try:
        return any(root.glob("Profiles/Runtimes/*.simruntime")) or any(
            root.glob("Volumes/*/Library/Developer/CoreSimulator/Profiles/Runtimes/*.simruntime"))
    except OSError:
        return False


def xcode_macos(run: Callable[[List[str]], Optional[str]], *, sim_root: Path = _SIM_ROOT) -> Tuple[Optional[str], bool]:
    ios_sim = _has_simruntime(sim_root)
    out = run(list(XCODE_SELECT_ARGV))
    selected = (out or "").strip()
    marker = ".app/Contents/Developer"
    if not selected or _CLT_MARK in selected or not selected.rstrip("/").endswith(marker):
        return None, ios_sim
    plist = Path(selected.rstrip("/")[: -len("/Developer")]) / "Info.plist"
    try:
        with plist.open("rb") as handle:
            version = plistlib.load(handle).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException, ValueError, ExpatError, AttributeError):
        return None, ios_sim
    return (version if isinstance(version, str) and version else None), ios_sim


def _vendor(text: str) -> Optional[str]:
    low = text.lower()
    for key, word in _VENDORS.items():
        if key in low:
            return word
    return None


def _vram_gb(text: Any) -> Optional[float]:
    parts = str(text or "").split()
    if len(parts) != 2 or not parts[0].replace(".", "", 1).isdigit():
        return None
    value = float(parts[0])
    return round(value / 1024.0 if parts[1].upper() == "MB" else value, 1) if parts[1].upper() in ("GB", "MB") else None


def _gpus_macos(out: Optional[str]) -> List[Dict[str, Any]]:
    try:
        rows = json.loads(out or "{}").get("SPDisplaysDataType")
    except (ValueError, AttributeError):
        return []
    found: List[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        model = str(row.get("sppci_model") or row.get("_name") or "")[:64]
        vendor = _vendor(str(row.get("spdisplays_vendor") or "")) or _vendor(model)
        if not model or vendor is None:
            continue
        discrete = vendor != "apple" and "builtin" not in str(row.get("sppci_bus") or "")
        vram = None if vendor == "apple" else _vram_gb(row.get("spdisplays_vram") or row.get("spdisplays_vram_shared"))
        found.append({"vendor": vendor, "model": model, "vram_gb": vram, "discrete": discrete})
    return found


def _gpus_nvidia(out: Optional[str]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for line in (out or "").splitlines():
        name, _, mib = line.rpartition(",")
        if not name.strip() or not mib.strip().isdigit():
            continue
        found.append({"vendor": "nvidia", "model": name.strip()[:64], "vram_gb": round(int(mib) / 1024.0, 1), "discrete": True})
    return found


def gpus(run: Callable[[List[str]], Optional[str]], system: str) -> List[Dict[str, Any]]:
    if system == "Darwin":
        return _gpus_macos(run(list(SYSTEM_PROFILER_ARGV)))[:MAX_GPUS]
    if system in ("Linux", "Windows"):
        for argv in NVIDIA_SMI_ARGVS:
            found = _gpus_nvidia(run(list(argv)))
            if found:
                return found[:MAX_GPUS]
    return []


def _playwright_cache(system: str, home: Path) -> Path:
    if system == "Darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if system == "Windows":
        return home / "AppData" / "Local" / "ms-playwright"
    return home / ".cache" / "ms-playwright"


def _read_specs() -> Dict[str, Any]:
    from src.core.pack.machines import snapshot
    return snapshot.read_specs()


def run_probe(*, run: Optional[Callable[[List[str]], Optional[str]]] = None, system: Optional[str] = None, home: Optional[Path] = None,
              specs: Optional[Callable[[], Dict[str, Any]]] = None, now: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic,
              budget_s: float = PROBE_BUDGET_S, apps_dir: Path = Path("/Applications"), sim_root: Path = _SIM_ROOT) -> Dict[str, Any]:
    runner = run or _run
    sys_name = system or platform.system()
    home_dir = home or Path.home()
    start = monotonic()

    def bounded(argv: List[str]) -> Optional[str]:
        return runner(argv) if monotonic() - start + _timeout_for(argv) <= budget_s else None

    spec = (specs or _read_specs)()
    tools = find_tools(_expand(EXTRA_DIRS, home_dir), system=sys_name, apps_dir=apps_dir, home=home_dir)
    cache = _playwright_cache(sys_name, home_dir)
    try:
        tools["playwright_browsers"] = cache.is_dir() and any(cache.iterdir())
    except OSError:
        tools["playwright_browsers"] = False
    xcode, ios_sim = xcode_macos(bounded, sim_root=sim_root) if sys_name == "Darwin" else (None, False)
    return {"probed_at": float(now()), "os": _OS_FAMILY.get(sys_name, sys_name.lower()),
            "os_version": platform.mac_ver()[0] if sys_name == "Darwin" else platform.release(),
            "arch": spec.get("arch"), "chip": spec.get("chip"), "cores": spec.get("cores"), "mem_gb": spec.get("mem_total_gb"),
            "gpus": gpus(bounded, sys_name), "tools": tools, "xcode": xcode, "ios_sim": ios_sim, "brew": brew_path() is not None}


class CanKeeper:

    def __init__(self, state_dir: Path, *, clock: Callable[[], float] = time.time, labels: Callable[[], List[str]] = lambda: [],
                 probe: Callable[[], Dict[str, Any]] = run_probe) -> None:
        self._path = Path(state_dir) / "pack" / "can.json"
        self._clock, self._labels, self._probe = clock, labels, probe
        self._lock = threading.Lock()
        self._probing = threading.Lock()
        self._result: Optional[Dict[str, Any]] = self._load()
        self._last_attempt: Optional[float] = None
        self._installing: Optional[str] = None

    def _load(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        ok = isinstance(data, dict) and isinstance(data.get("probed_at"), (int, float)) and not isinstance(data.get("probed_at"), bool)
        return data if ok else None

    def _store(self, result: Dict[str, Any]) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(result, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except OSError as exc:
            log.warning("pack_can_store_failed", error=type(exc).__name__)

    def current(self) -> Dict[str, Any]:
        with self._lock:
            result, installing = self._result, self._installing
        return can_block.build(result, self._labels(), installing) if result else {}

    def due(self) -> bool:
        now = self._clock()
        with self._lock:
            result, attempt = self._result, self._last_attempt
        if attempt is not None and 0 <= now - attempt < MIN_GAP_S:
            return False
        return result is None or not 0 <= now - float(result["probed_at"]) < DUE_AFTER_S

    def refresh(self, reason: str) -> Tuple[Dict[str, Any], bool]:
        if not self._probing.acquire(blocking=False):
            return self.current(), False
        try:
            now = self._clock()
            with self._lock:
                attempt = self._last_attempt
                skip = attempt is not None and 0 <= now - attempt < MIN_GAP_S
                if not skip:
                    self._last_attempt = now
            if skip:
                return self.current(), False
            result = self._probe()
            with self._lock:
                self._result = result
            self._store(result)
            log.info("pack_can_probed", reason=reason)
            return self.current(), True
        finally:
            self._probing.release()

    def set_installing(self, tool: Optional[str]) -> None:
        if tool is not None and tool not in can_block.VOCAB:
            raise PackInputError(f"unknown tool: {tool}")
        with self._lock:
            self._installing = tool
