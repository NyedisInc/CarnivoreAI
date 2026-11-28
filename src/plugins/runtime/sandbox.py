
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
from typing import Dict, List, Optional, Sequence, Tuple

RUNNER_SOURCE = Path(__file__).with_name("runner.py")
SOCK_CLI_SOURCE = Path(__file__).with_name("sock_cli.py")
SDK_SOURCE = Path(__file__).resolve().parent.parent / "sdk_py"
SDK_PACKAGE = "cplug_sdk"
SDK_TS_SOURCE = Path(__file__).resolve().parent.parent / "sdk_ts"
RUNTIME_DIR_NAME = "cplug-runtime"
PROFILES_DIR_NAME = "profiles"
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
    runtime_kind: str = "python"
    read_roots: Tuple[Path, ...] = ()
    exec_paths: Tuple[Path, ...] = ()
    allow_fork: bool = False
    socket_path: Optional[Path] = None
    carnivore_bin: Optional[Path] = None
    plugin_id: str = ""
    run_mode: str = "rpc"
    pythonpath_extra: Tuple[Path, ...] = ()

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def profile_path(self) -> Path:
        return profile_path_for(self.data_dir)


@dataclass(frozen=True)
class ResolvedRuntime:

    kind: str
    interpreter: Path
    stdlib_root: Path
    primary_exec: Path
    exec_paths: Tuple[Path, ...] = ()
    read_roots: Tuple[Path, ...] = ()
    allow_fork: bool = False
    args: Tuple[str, ...] = ()
    pythonpath_extra: Tuple[Path, ...] = ()


def profile_path_for(data_dir: Path) -> Path:
    return data_dir.parent / PROFILES_DIR_NAME / f"{data_dir.name}.sb"


def write_profile(layout: Layout) -> Path:
    path = layout.profile_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_profile(layout), encoding="utf-8")
    (layout.data_dir / "profile.sb").unlink(missing_ok=True)
    return path


def remove_profile(data_dir: Path) -> None:
    profile_path_for(data_dir).unlink(missing_ok=True)


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
        profile = write_profile(layout)
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
    if sys.platform != "darwin" or "Python.framework" not in str(interpreter):
        return Path(os.path.realpath(sys.base_prefix))
    return interpreter.parents[4]


def _python_runtime() -> Tuple[Path, Path]:
    if sys.platform == "darwin":
        interp = find_interpreter()
        return interp, stdlib_root(interp)
    interp = Path(os.path.realpath(sys.executable))
    return interp, Path(os.path.realpath(sys.base_prefix))


def _find_node() -> Path:
    candidates: List[Path] = []
    which = shutil.which("node")
    if which:
        candidates.append(Path(which))
    candidates.extend([Path("/opt/homebrew/bin/node"), Path("/usr/local/bin/node")])
    candidates.extend(sorted(Path.home().glob(".nvm/versions/node/*/bin/node"), reverse=True))
    for cand in candidates:
        if cand.is_file():
            return Path(os.path.realpath(cand))
    raise SandboxUnavailable("node runtime was not found")


def _find_bun() -> Path:
    candidates: List[Path] = []
    which = shutil.which("bun")
    if which:
        candidates.append(Path(which))
    candidates.extend([Path.home() / ".bun" / "bin" / "bun", Path("/opt/homebrew/bin/bun"), Path("/usr/local/bin/bun")])
    for cand in candidates:
        if cand.is_file():
            return Path(os.path.realpath(cand))
    raise SandboxUnavailable("bun runtime was not found")


def _find_bash() -> Path:
    for cand in (Path("/bin/bash"), *( [Path(w)] if (w := shutil.which("bash")) else [] )):
        if cand.is_file():
            return Path(os.path.realpath(cand))
    raise SandboxUnavailable("bash runtime was not found")


def resolve_runtime(cmd: Sequence[str], code_dir: Path, *, allow_fork_for_bin: bool = False) -> ResolvedRuntime:
    code_real = Path(os.path.realpath(code_dir))
    py_interp, py_sroot = _python_runtime()
    if not cmd:
        return ResolvedRuntime("python", py_interp, py_sroot, py_interp, (py_interp,), (), allow_fork_for_bin, ())
    cmd0 = cmd[0]
    exe = Path(cmd0).name.lower()
    if exe.startswith("python"):
        return ResolvedRuntime("python", py_interp, py_sroot, py_interp, (py_interp,), (), allow_fork_for_bin, tuple(cmd[1:]))
    if exe == "uv":
        args: List[str] = []
        skip_next = False
        seen_run = False
        for arg in cmd[1:]:
            if skip_next:
                skip_next = False
                continue
            if arg in ("-p", "--python", "--with", "--directory", "--project"):
                skip_next = True
                continue
            if not seen_run and arg == "run":
                seen_run = True
                continue
            if arg.startswith("-") and not args:
                continue
            args.append(arg)
        read_roots: List[Path] = []
        py_extra: List[Path] = []
        venv_dir = code_real / ".venv"
        if venv_dir.is_dir():
            venv_real = Path(os.path.realpath(venv_dir))
            if venv_real.is_relative_to(code_real):
                read_roots.append(venv_real)
                for sp in sorted(venv_real.glob("lib/python*/site-packages")):
                    sp_real = Path(os.path.realpath(sp))
                    if sp_real.is_dir() and sp_real.is_relative_to(code_real):
                        py_extra.append(sp_real)
        return ResolvedRuntime(
            "uv", py_interp, py_sroot, py_interp, (py_interp,), tuple(read_roots), allow_fork_for_bin, tuple(args), tuple(py_extra)
        )
    if exe == "node":
        node_exe = _find_node()
        roots = [node_exe.parent.parent]
        roots.extend(_homebrew_dependency_roots(node_exe))
        return ResolvedRuntime("node", py_interp, py_sroot, node_exe, (node_exe,), tuple(dict.fromkeys(roots)), allow_fork_for_bin, tuple(cmd[1:]))
    if exe == "bun":
        bun_exe = _find_bun()
        roots = [bun_exe.parent.parent]
        roots.extend(_homebrew_dependency_roots(bun_exe))
        return ResolvedRuntime("bun", py_interp, py_sroot, bun_exe, (bun_exe,), tuple(dict.fromkeys(roots)), allow_fork_for_bin, tuple(cmd[1:]))
    if exe in ("bash", "sh"):
        bash_exe = _find_bash()
        sh_execs = tuple(_dedupe_paths([p for p in (bash_exe, Path("/bin/bash"), Path("/bin/sh"), Path("/usr/bin/env")) if p.exists()]))
        return ResolvedRuntime("bash", py_interp, py_sroot, bash_exe, sh_execs or (bash_exe,), (), True, tuple(cmd[1:]))
    target = Path(os.path.realpath(code_real / cmd0))
    if not target.is_relative_to(code_real) or not target.is_file():
        raise SandboxUnavailable(f"compiled plugin executable {cmd0!r} was not found inside code_dir")
    if target.suffix.lower() in (".sh", ".bash"):
        bash_exe = _find_bash()
        sh_execs = tuple(_dedupe_paths([target, *(p for p in (bash_exe, Path("/bin/bash"), Path("/bin/sh"), Path("/usr/bin/env")) if p.exists())]))
        return ResolvedRuntime("bash", py_interp, py_sroot, target, sh_execs, (), True, tuple(cmd[1:]))
    return ResolvedRuntime("binary", py_interp, py_sroot, target, (target,), (), allow_fork_for_bin, tuple(cmd[1:]))


def _homebrew_dependency_roots(exe: Path) -> List[Path]:
    roots = [Path("/opt/homebrew/opt"), Path("/opt/homebrew/Cellar"), *sorted(Path("/opt/homebrew/etc").glob("openssl@*"))]
    if not str(exe).startswith("/opt/homebrew/"):
        return []
    return [r for r in roots if r.is_dir()]


def copy_runtime(state_dir: Path, app_version: str) -> Path:
    if not app_version or not all(c.isalnum() or c in ".-_+" for c in app_version) or app_version.startswith("."):
        raise ValueError("app_version must be a plain version string")
    target = Path(state_dir) / RUNTIME_DIR_NAME / app_version
    if target.exists():
        _make_writable(target)
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(RUNNER_SOURCE, target / "runner.py")
    if SOCK_CLI_SOURCE.is_file():
        shutil.copy2(SOCK_CLI_SOURCE, target / "sock_cli.py")
    shutil.copytree(SDK_SOURCE, target / SDK_PACKAGE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if SDK_TS_SOURCE.is_dir():
        ts_pkg_dir = target / "node_modules" / "@carnivore" / "plugin-sdk"
        ts_pkg_dir.mkdir(parents=True, exist_ok=True)
        for fname in ("package.json", "node_preload.mjs"):
            src_file = SDK_TS_SOURCE / fname
            if src_file.is_file():
                shutil.copy2(src_file, ts_pkg_dir / fname)
        dist_dir = SDK_TS_SOURCE / "dist"
        if dist_dir.is_dir():
            shutil.copytree(dist_dir, ts_pkg_dir / "dist")
        sdk_ts_dir = target / "sdk_ts"
        sdk_ts_dir.mkdir(parents=True, exist_ok=True)
        preload_src = SDK_TS_SOURCE / "node_preload.mjs"
        if preload_src.is_file():
            shutil.copy2(preload_src, sdk_ts_dir / "node_preload.mjs")
        bun_tsconfig = {
            "compilerOptions": {
                "paths": {
                    "@carnivore/plugin-sdk": [str(ts_pkg_dir / "dist" / "index.js")],
                    "@carnivore/plugin-sdk/testing": [str(ts_pkg_dir / "dist" / "testing.js")],
                }
            }
        }
        (sdk_ts_dir / "bun_paths.json").write_text(json.dumps(bun_tsconfig), encoding="utf-8")
    for path in [target, *target.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o444)
    return target


def _make_writable(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        item.chmod(item.stat().st_mode | stat.S_IWUSR)


def ancestors(path: Path) -> List[Path]:
    return [p for p in Path(path).parents]


def _dedupe_paths(paths: Sequence[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for p in paths:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def _sock_python_for(layout: Layout) -> Path:
    if layout.runtime_kind in ("python", "uv"):
        return layout.interpreter
    try:
        return _python_runtime()[0]
    except SandboxUnavailable:
        return Path(os.path.realpath(sys.executable))


def render_profile(layout: Layout) -> str:
    sock_python = _sock_python_for(layout) if layout.carnivore_bin is not None else None
    def rp(p: Path) -> Path:
        return Path(os.path.realpath(p))
    reads = _dedupe_paths([rp(layout.stdlib_root), rp(layout.runtime_dir), rp(layout.code_dir), rp(layout.files_dir), *(rp(p) for p in layout.read_roots)])
    bash_execs = [rp(p) for p in (Path("/bin/sh"), Path("/bin/bash"), Path("/usr/bin/env")) if p.exists()]
    execs = _dedupe_paths([
        rp(layout.interpreter),
        *(rp(p) for p in layout.exec_paths),
        *([rp(layout.carnivore_bin), rp(sock_python)] if layout.carnivore_bin is not None and sock_python is not None else []),
        *([Path("/bin/sh"), Path("/bin/bash")] if layout.allow_fork and layout.carnivore_bin is not None else []),
        *(bash_execs if layout.runtime_kind == "bash" else []),
    ])
    bash_literals = [p for p in (Path("/bin/sh"), Path("/bin/bash"), Path("/private/var/select/sh"), Path("/usr/bin/env")) if p.exists()]
    read_literals = _dedupe_paths([
        *([rp(layout.carnivore_bin), rp(sock_python)] if layout.carnivore_bin is not None and sock_python is not None else []),
        *([Path("/bin/sh"), Path("/bin/bash"), Path("/private/var/select/sh")] if layout.allow_fork and layout.carnivore_bin is not None else []),
        *(bash_literals if layout.runtime_kind == "bash" else []),
    ])
    map_exec_subpaths = _dedupe_paths([
        rp(layout.stdlib_root),
        *(rp(p) for p in layout.read_roots),
        *([rp(layout.code_dir)] if layout.runtime_kind == "binary" else []),
    ])
    meta_targets = [*reads, *execs, *read_literals]
    if layout.socket_path is not None:
        meta_targets.append(rp(layout.socket_path))
    meta: List[Path] = []
    for p in meta_targets:
        for a in ancestors(p):
            if a not in meta:
                meta.append(a)
    read_clauses = [f"(subpath {_quote(p)})" for p in reads] + [f"(literal {_quote(p)})" for p in read_literals]
    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        "(allow process-exec " + " ".join(f"(literal {_quote(p)})" for p in execs) + ")",
        "(allow process-fork)" if layout.allow_fork else "(deny process-fork)",
        "(allow file-read* " + " ".join(read_clauses) + ")",
        "(allow file-map-executable " + " ".join(f"(subpath {_quote(p)})" for p in map_exec_subpaths) + ")",
        "(allow file-read-metadata " + " ".join(f"(literal {_quote(p)})" for p in meta) + ")",
    ]
    if layout.runtime_kind == "bun":
        lines.append("(allow file-read-data " + " ".join(f"(literal {_quote(p)})" for p in ancestors(rp(layout.files_dir))) + ")")
    lines += [
        f"(allow file-write* (subpath {_quote(rp(layout.files_dir))}))",
        "(deny network*)",
    ]
    if layout.socket_path is not None:
        sock_real = Path(os.path.realpath(layout.socket_path))
        lines.append(f"(allow network-outbound (remote unix-socket (path-literal {_quote(sock_real)})))")
    lines.extend([
        '(deny mach-lookup (global-name-prefix "com.apple.security"))',
        '(deny sysctl-read (sysctl-name-prefix "kern.proc."))',
    ])
    return "\n".join(lines) + "\n"


def allow_env(layout: Layout, locale: str = "en_US.UTF-8", unrestricted: bool = False) -> Dict[str, str]:
    env: Dict[str, str] = {
        "PATH": UNRESTRICTED_PATH if unrestricted else SAFE_PATH,
        "HOME": str(layout.data_dir),
        "LANG": locale,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if layout.socket_path is not None:
        env["CARNIVORE_PLUGIN_SOCK"] = os.path.realpath(layout.socket_path)
    if layout.carnivore_bin is not None:
        env["CARNIVORE_BIN"] = str(layout.carnivore_bin)
        env["CARNIVORE_SOCK_CLIENT"] = str(layout.runtime_dir / "sock_cli.py")
        env["CARNIVORE_SOCK_PYTHON"] = str(_sock_python_for(layout))
    if layout.plugin_id:
        env["CARNIVORE_PLUGIN_ID"] = layout.plugin_id
        env["CARNIVORE_DATA_DIR"] = str(layout.files_dir)
        env["CARNIVORE_PLUGIN_MODE"] = layout.run_mode
    if layout.pythonpath_extra:
        extra = os.pathsep.join(str(p) for p in layout.pythonpath_extra)
        env["PYTHONPATH"] = extra
        env["CARNIVORE_EXTRA_SITE"] = extra
    if layout.runtime_kind in ("node", "bun"):
        node_modules_dir = layout.runtime_dir / "node_modules"
        sdk_ts_dir = node_modules_dir / "@carnivore" / "plugin-sdk"
        env["NODE_PATH"] = str(node_modules_dir)
        env["CARNIVORE_SDK_TS_DIR"] = str(sdk_ts_dir)
    return env


def bwrap_available() -> bool:
    return sys.platform.startswith("linux") and shutil.which("bwrap") is not None


def unshare_prefix() -> Optional[List[str]]:
    if not sys.platform.startswith("linux"):
        return None
    exe = shutil.which("unshare")
    if exe is None:
        return None
    if os.geteuid() == 0:
        setpriv = shutil.which("setpriv")
        if setpriv is None:
            return None
        prefix = [exe, "-n", setpriv, "--reuid", "65534", "--regid", "65534", "--clear-groups", "--no-new-privs"]
    else:
        prefix = [exe, "-rn"]
    try:
        done = subprocess.run([*prefix, "true"], capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return prefix if done.returncode == 0 else None


def landlock_available() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        return "landlock" in Path("/sys/kernel/security/lsm").read_text(encoding="utf-8")
    except OSError:
        return False


def landlock_ruleset(layout: Layout) -> Dict[str, Tuple[str, ...]]:
    ro = [
        str(layout.interpreter),
        str(layout.stdlib_root),
        str(layout.runtime_dir),
        str(layout.code_dir),
        *(str(p) for p in layout.read_roots),
        *(str(p) for p in layout.exec_paths),
    ]
    if layout.carnivore_bin is not None:
        ro.append(str(layout.carnivore_bin))
        ro.append(str(_sock_python_for(layout)))
    rw = [str(layout.files_dir)]
    if layout.socket_path is not None:
        rw.append(str(Path(os.path.realpath(layout.socket_path))))
    return {"ro": tuple(dict.fromkeys(ro)), "rw": tuple(dict.fromkeys(rw))}


def build_linux_command(layout: Layout, cmd: Sequence[str]) -> List[str]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise SandboxUnavailable("bwrap is not available on Linux")
    argv = [bwrap, "--unshare-net", "--unshare-pid", "--die-with-parent", "--new-session"]
    for sys_dir in ("/usr", "/lib", "/lib64", "/bin", "/etc/alternatives"):
        if Path(sys_dir).exists():
            argv.extend(["--ro-bind", sys_dir, sys_dir])
    argv.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"])
    ro_candidates: List[Path] = [
        layout.interpreter,
        layout.stdlib_root,
        layout.runtime_dir,
        layout.code_dir,
        *layout.read_roots,
        *layout.exec_paths,
    ]
    if layout.carnivore_bin is not None:
        ro_candidates.append(layout.carnivore_bin)
        ro_candidates.append(_sock_python_for(layout))
    for ro in _dedupe_paths(ro_candidates):
        if ro.exists():
            argv.extend(["--ro-bind", str(ro), str(ro)])
    argv.extend(["--bind", str(layout.files_dir), str(layout.files_dir)])
    if layout.socket_path is not None:
        sock_real = Path(os.path.realpath(layout.socket_path))
        if sock_real.exists():
            argv.extend(["--bind", str(sock_real), str(sock_real)])
    argv.extend(["--chdir", str(layout.files_dir), "--", *cmd])
    return argv


def build_polyglot_command(layout: Layout, profile_path: Optional[Path], cmd: Sequence[str], *, unrestricted: bool = False) -> List[str]:
    if unrestricted:
        return list(cmd)
    if sys.platform == "darwin":
        if not os.path.exists("/usr/bin/sandbox-exec") or profile_path is None:
            raise SandboxUnavailable("sandbox-exec is not available")
        return ["/usr/bin/sandbox-exec", "-f", str(profile_path), *cmd]
    if bwrap_available():
        return build_linux_command(layout, cmd)
    prefix = unshare_prefix()
    if prefix is not None:
        return [*prefix, *cmd]
    raise SandboxUnavailable("no supported OS sandbox (macOS sandbox-exec, Linux bwrap, or unshare) is available")


def _runner_cmd(layout: Layout, entry: str, fsize_bytes: int) -> List[str]:
    return [
        str(layout.interpreter),
        "-I",
        "-B",
        "-X",
        f"pycache_prefix={layout.runtime_dir / NO_PYCACHE}",
        str(layout.runtime_dir / "runner.py"),
        str(layout.code_dir),
        entry,
        str(OPEN_FILES_LIMIT),
        str(fsize_bytes),
    ]


def build_command(layout: Layout, profile_path: Path, entry: str, fsize_bytes: int) -> List[str]:
    cmd = _runner_cmd(layout, entry, fsize_bytes)
    if sys.platform != "darwin":
        return build_polyglot_command(layout, profile_path, cmd, unrestricted=False)
    return ["/usr/bin/sandbox-exec", "-f", str(profile_path), *cmd]


def build_unrestricted_command(layout: Layout, entry: str, fsize_bytes: int) -> List[str]:
    return _runner_cmd(layout, entry, fsize_bytes)
