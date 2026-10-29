
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import structlog

from src.core.desktop_app.payload_bytecode import bytecode_flags

log = structlog.get_logger(__name__)

LINK_DIR = "/usr/local/bin"
LINK_PATH = "/usr/local/bin/carnivore"
OSASCRIPT_TIMEOUT_S = 120

OsascriptRunner = Callable[[str, int], Tuple[int, str]]


def source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def shim_path(state: Path) -> Path:
    return Path(state) / "bin" / "carnivore"


def shim_content(root: Path, python: str, flags: Sequence[str] = ()) -> str:
    extra = "".join(f" {shlex.quote(flag)}" for flag in flags)
    return "\n".join([
        "#!/bin/sh",
        "# Written by the Carnivore server at every start. Do not edit.",
        f"PYTHONPATH={shlex.quote(str(root))}${{PYTHONPATH:+:$PYTHONPATH}}",
        "export PYTHONPATH",
        f"exec {shlex.quote(python)}{extra} -m src.tui \"$@\"",
        "",
    ])


def write_shim(state: Path, root: Optional[Path] = None, python: Optional[str] = None) -> Path:
    target = shim_path(state)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    text = shim_content(root or source_root(), python or sys.executable, bytecode_flags())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o755)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    return target


def _is_carnivore_shim(target: str) -> bool:
    p = Path(target)
    return p.name == "carnivore" and p.parent.name == "bin" and "carnivore" in str(p.parent.parent).lower()


def link_state(shim: Path, link_path: str = LINK_PATH) -> str:
    try:
        if not os.path.islink(link_path):
            return "foreign" if os.path.lexists(link_path) else "missing"
        target = os.readlink(link_path)
    except OSError as exc:
        log.warning("cli_command_link_unreadable", link_path=link_path, error=str(exc))
        return "foreign"
    if target == str(shim):
        return "installed"
    if not os.path.exists(link_path) or _is_carnivore_shim(target):
        return "stale"
    return "foreign"


def manual_command(shim: Path, link_dir: str = LINK_DIR, link_path: str = LINK_PATH) -> str:
    return f"sudo mkdir -p {shlex.quote(link_dir)} && sudo ln -sfn {shlex.quote(str(shim))} {shlex.quote(link_path)}"


def checkout_command(root: Path, python: str) -> str:
    extra = "".join(f" {shlex.quote(flag)}" for flag in bytecode_flags())
    return f"cd {shlex.quote(str(root))} && {shlex.quote(python)}{extra} -m src.tui"


def privileged_command(shim: Path, link_dir: str = LINK_DIR, link_path: str = LINK_PATH) -> str:
    return f"/bin/mkdir -p {shlex.quote(link_dir)} && /bin/ln -sfn {shlex.quote(str(shim))} {shlex.quote(link_path)}"


def apple_script(shell_cmd: str) -> str:
    esc = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    return f'do shell script "{esc}" with administrator privileges'


def status_body(state: Path, link_path: str = LINK_PATH) -> Dict[str, str]:
    shim = shim_path(state)
    return {
        "state": link_state(shim, link_path),
        "command": "carnivore tui",
        "link_path": link_path,
        "shim_path": str(shim),
        "manual_command": manual_command(shim, str(Path(link_path).parent), link_path),
        "run_from_checkout": checkout_command(source_root(), sys.executable),
    }


def run_osascript(script: str, timeout: int) -> Tuple[int, str]:
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stderr or ""


def _link_directly(shim: Path, link_path: str) -> None:
    tmp = f"{link_path}.tmp-{os.getpid()}"
    try:
        os.symlink(str(shim), tmp)
        os.replace(tmp, link_path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def install(
    state: Path,
    link_path: str = LINK_PATH,
    runner: OsascriptRunner = run_osascript,
    timeout: int = OSASCRIPT_TIMEOUT_S,
) -> Dict[str, Any]:
    try:
        shim = write_shim(state)
    except OSError as exc:
        log.warning("cli_command_shim_write_failed", error=str(exc))
        return _result("failed", state, link_path, "could not write the command shim")
    before = link_state(shim, link_path)
    if before == "installed":
        return _result("already_installed", state, link_path, "the command is already installed")
    if before == "foreign":
        return _result("foreign", state, link_path, f"{link_path} exists and is not the carnivore command, left alone")
    link_dir = str(Path(link_path).parent)
    if os.path.isdir(link_dir) and os.access(link_dir, os.W_OK | os.X_OK):
        try:
            _link_directly(shim, link_path)
        except OSError as exc:
            log.warning("cli_command_link_failed", error=str(exc))
            return _result("failed", state, link_path, "could not create the link")
        return _result("installed", state, link_path, "installed, run carnivore tui in a terminal")
    script = apple_script(privileged_command(shim, link_dir, link_path))
    try:
        code, err = runner(script, timeout)
    except subprocess.TimeoutExpired:
        log.warning("cli_command_prompt_timed_out")
        return _result("timed_out", state, link_path, "the admin prompt timed out")
    except OSError as exc:
        log.warning("cli_command_osascript_unavailable", error=str(exc))
        return _result("failed", state, link_path, "could not open the admin prompt")
    if code == 0:
        return _result("installed", state, link_path, "installed, run carnivore tui in a terminal")
    if "-128" in err or "user canceled" in err.lower():
        return _result("cancelled", state, link_path, "cancelled at the admin prompt")
    log.warning("cli_command_install_failed", code=code)
    return _result("failed", state, link_path, "the install failed, use the manual command")


def _result(outcome: str, state: Path, link_path: str, detail: str) -> Dict[str, Any]:
    return {"outcome": outcome, "state": link_state(shim_path(state), link_path), "detail": detail}
