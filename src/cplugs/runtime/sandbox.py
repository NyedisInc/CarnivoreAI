
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

RUNNER_SOURCE = Path(__file__).with_name("runner.py")
SDK_SOURCE = Path(__file__).resolve().parent.parent / "sdk_py"
SDK_PACKAGE = "cplug_sdk"
RUNTIME_DIR_NAME = "cplug-runtime"
SAFE_PATH = "/usr/bin:/bin"
UNRESTRICTED_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
OPEN_FILES_LIMIT = 64
NO_PYCACHE = ".no-pycache"
MIN_PYTHON_MINOR = 12
FRAMEWORK_ROOTS = ("/opt/homebrew/Frameworks", "/usr/local/Frameworks", "/Library/Frameworks")
PROBE_TIMEOUT_S = 20.0
_BAD_CHARS = ('"', "\\", "\n", "\r", "\x00", "(", ")", ";")


class SandboxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Layout:

    interpreter: Path
    stdlib_root: Path
    runtime_dir: Path
    code_dir: Path
    data_dir: Path

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


def _quote(path: Path) -> str:
    text = str(path)
    if any(c in text for c in _BAD_CHARS):
        raise ValueError(f"path cannot appear in a sandbox profile: {text!r}")
    return f'"{text}"'


def framework_interpreter(prefix: str = "") -> Path:
    base = Path(os.path.realpath(prefix or sys.base_prefix))
    found = base / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
    if sys.platform != "darwin" or not found.is_file():
        raise SandboxUnavailable("the framework interpreter was not found")
    return found


def find_interpreter(prefix: str = "", roots: Sequence[str] = FRAMEWORK_ROOTS) -> Path:
    try:
        return framework_interpreter(prefix)
    except SandboxUnavailable:
        pass
    versions = []
    for root in roots:
        for folder in (Path(root) / "Python.framework" / "Versions").glob("3.*"):
            minor = folder.name.partition(".")[2]
            if minor.isdigit() and int(minor) >= MIN_PYTHON_MINOR:
                versions.append((int(minor), folder))
    for _minor, folder in sorted(versions, key=lambda item: item[0], reverse=True):
        try:
            return framework_interpreter(str(folder))
        except SandboxUnavailable:
            continue
    raise SandboxUnavailable(f"no framework Python 3.{MIN_PYTHON_MINOR}+ with Python.app was found (pyenv, uv and venv builds have none)")


@dataclass(frozen=True)
class ProbeResult:

    interpreter: Path
    ran: bool
    denied_write_refused: bool
    allowed_write_ok: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.ran and self.denied_write_refused and self.allowed_write_ok


_PROBE_SCRIPT = (
    "import json,sys\n"
    "r={'denied_refused':False,'allowed_ok':False}\n"
    "try:\n open(sys.argv[2],'w').write('x')\n"
    "except OSError:\n r['denied_refused']=True\n"
    "try:\n open(sys.argv[1]+'/ok','w').write('x'); r['allowed_ok']=True\n"
    "except OSError:\n pass\n"
    "print(json.dumps(r))\n"
)


def probe(interpreter: Optional[Path] = None) -> ProbeResult:
    try:
        interp = interpreter or find_interpreter()
    except SandboxUnavailable as exc:
        return ProbeResult(Path(""), False, False, False, str(exc))
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return ProbeResult(interp, False, False, False, "sandbox-exec is not available")
    with tempfile.TemporaryDirectory(prefix="cplug-probe-") as raw:
        root = Path(os.path.realpath(raw))
        runtime, code, data = root / "runtime", root / "code", root / "data"
        for folder in (runtime, code, data / "files"):
            folder.mkdir(parents=True)
        layout = Layout(interpreter=interp, stdlib_root=stdlib_root(interp), runtime_dir=runtime, code_dir=code, data_dir=data)
        profile = data / "profile.sb"
        profile.write_text(render_profile(layout))
        argv = ["/usr/bin/sandbox-exec", "-f", str(profile), str(interp), "-I", "-B", "-c", _PROBE_SCRIPT,
                str(layout.files_dir), str(data / "denied.txt")]
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, env=allow_env(layout), check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return ProbeResult(interp, False, False, False, f"{type(exc).__name__}: {exc}")
        try:
            seen = json.loads(done.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return ProbeResult(interp, False, False, False, f"exit {done.returncode}: {done.stderr.strip()[-200:]}")
        refused = bool(seen.get("denied_refused")) and not (data / "denied.txt").exists()
        return ProbeResult(interp, True, refused, bool(seen.get("allowed_ok")))


def stdlib_root(interpreter: Path) -> Path:
    return interpreter.parents[4]


def copy_runtime(state_dir: Path, app_version: str) -> Path:
    if not app_version or not all(c.isalnum() or c in ".-_+" for c in app_version) or app_version.startswith("."):
        raise ValueError("app_version must be a plain version string")
    target = Path(state_dir) / RUNTIME_DIR_NAME / app_version
    if target.exists():
        _make_writable(target)
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(RUNNER_SOURCE, target / "runner.py")
    shutil.copytree(SDK_SOURCE, target / SDK_PACKAGE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in [target, *target.rglob("*")]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    return target


def _make_writable(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        item.chmod(item.stat().st_mode | stat.S_IWUSR)


def ancestors(path: Path) -> List[Path]:
    return [p for p in Path(path).parents]


def render_profile(layout: Layout) -> str:
    reads = [layout.stdlib_root, layout.runtime_dir, layout.code_dir, layout.files_dir]
    meta: List[Path] = []
    for p in reads + [layout.interpreter]:
        for a in ancestors(p):
            if a not in meta:
                meta.append(a)
    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        f"(allow process-exec (literal {_quote(layout.interpreter)}))",
        "(deny process-fork)",
        "(allow file-read* " + " ".join(f"(subpath {_quote(p)})" for p in reads) + ")",
        f"(allow file-map-executable (subpath {_quote(layout.stdlib_root)}))",
        "(allow file-read-metadata " + " ".join(f"(literal {_quote(p)})" for p in meta) + ")",
        f"(allow file-write* (subpath {_quote(layout.files_dir)}))",
        "(deny network*)",
        '(deny mach-lookup (global-name-prefix "com.apple.security"))',
        '(deny sysctl-read (sysctl-name-prefix "kern.proc."))',
    ]
    return "\n".join(lines) + "\n"


def allow_env(layout: Layout, locale: str = "en_US.UTF-8", unrestricted: bool = False) -> Dict[str, str]:
    return {"PATH": UNRESTRICTED_PATH if unrestricted else SAFE_PATH, "HOME": str(layout.data_dir), "LANG": locale, "PYTHONDONTWRITEBYTECODE": "1"}


def build_command(layout: Layout, profile_path: Path, entry: str, fsize_bytes: int) -> List[str]:
    return ["/usr/bin/sandbox-exec", "-f", str(profile_path), str(layout.interpreter), "-I", "-B",
            "-X", f"pycache_prefix={layout.runtime_dir / NO_PYCACHE}",
            str(layout.runtime_dir / "runner.py"), str(layout.code_dir), entry,
            str(OPEN_FILES_LIMIT), str(fsize_bytes)]


def build_unrestricted_command(layout: Layout, entry: str, fsize_bytes: int) -> List[str]:
    return build_command(layout, Path(os.devnull), entry, fsize_bytes)[3:]
