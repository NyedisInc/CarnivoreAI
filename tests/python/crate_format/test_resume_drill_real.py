
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterator, Optional

import pytest

from src.core.claude_folder_trust import CLAUDE_JSON_NAME, TRUST_TRUSTED, folder_trust, load_trust_map
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_format.extract import extract_conversation
from src.core.crate_format.reader import open_crate
from tests.python.crate_format.golden_read import V1
from tests.python.inventory.world import CONV_A
from tests.socket_guard import derive_test_socket

FLAG = "CARNIVORE_CRATE_RESUME_DRILL"
PARENT_ENV = "CARNIVORE_CRATE_DRILL_PARENT"
FIXTURE = V1 / "session-own.crate"
LAST_PROMPT = "plan it"
STARTUP_MARKERS = ("trust the files", "trust this folder", "Do you trust", "Allow external CLAUDE.md file imports")
NOT_FOUND_MARKERS = ("No conversation found",)
EXIT_MARK = "CRATE_DRILL_EXITED"
WAIT_S, EXIT_WAIT_S, POLL_S = 60.0, 15.0, 0.5
KEEP_ENV = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "LC_ALL", "TMPDIR", "CLAUDE_CONFIG_DIR")


def _profile() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _claude_json() -> Path:
    return Path(os.environ["CLAUDE_CONFIG_DIR"]) / CLAUDE_JSON_NAME if os.environ.get("CLAUDE_CONFIG_DIR") else \
        Path.home() / CLAUDE_JSON_NAME


def _logged_in(path: Path) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(document, dict) and bool(document.get("oauthAccount"))


def _trusted_parent() -> Optional[Path]:
    trust = load_trust_map(_claude_json())
    for candidate in (os.environ.get(PARENT_ENV), os.environ.get("TMPDIR") or "/tmp"):
        if candidate and os.path.isdir(candidate):
            real = os.path.realpath(candidate)
            if folder_trust(real, trust) == TRUST_TRUSTED:
                return Path(real)
    return None


@pytest.fixture
def claude_bin() -> str:
    if os.environ.get(FLAG) != "1":
        pytest.skip(f"opt-in: set {FLAG}=1 to run the real resume drill")
    found = shutil.which("claude")
    if not found:
        pytest.skip("claude_not_on_path")
    if not _logged_in(_claude_json()):
        pytest.skip("claude_not_logged_in")
    return found


def _tmux(socket: str, *args: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True, timeout=20, env=env)


def _pane(socket: str) -> str:
    return _tmux(socket, "capture-pane", "-p", "-J", "-S", "-500", "-t", "drill").stdout


def _wait_for(socket: str, needles: tuple, seconds: float) -> Optional[str]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = _pane(socket)
        for needle in needles:
            if needle in text:
                return needle
        time.sleep(POLL_S)
    return None


def _to_trash(path: Path) -> None:
    if path.exists():
        shutil.move(str(path), str(Path.home() / ".Trash" / f"{path.name}-{int(time.time())}"))


@pytest.fixture
def drill_place(tmp_path: Path) -> Iterator[Dict[str, Path]]:
    parent = _trusted_parent()
    if parent is None:
        pytest.skip("no_trusted_parent")
    folder = parent / f"crate-drill-{os.getpid()}-{secrets.token_hex(3)}"
    enc = _profile() / "projects" / slugify_project_dir(str(folder))
    assert not folder.exists() and not enc.exists()
    with open_crate(FIXTURE) as reader:
        record = next(r for r in reader.files() if r.conversation_id == CONV_A and r.role == "transcript")
        out = extract_conversation(reader, CONV_A, tmp_path / "extract", enc_for=slugify_project_dir,
                                   target_cwd=str(folder))
    source = tmp_path / "extract" / f"projects/{out.enc_folder}/{CONV_A}.jsonl"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == record.content_sha256
    folder.mkdir()
    try:
        enc.mkdir(parents=False)
        shutil.copyfile(source, enc / f"{CONV_A}.jsonl")
        yield {"folder": folder, "enc": enc}
    finally:
        _to_trash(enc)
        _to_trash(folder)


def test_claude_resumes_the_extracted_conversation(claude_bin: str, drill_place: Dict[str, Path]) -> None:
    socket = derive_test_socket("crate_drill")
    env = {k: os.environ[k] for k in KEEP_ENV if os.environ.get(k)}
    env["TERM"] = "xterm-256color"
    command = f"{shlex.quote(claude_bin)} --resume {CONV_A} --fork-session; echo {EXIT_MARK} $?; sleep 30"
    started = _tmux(socket, "new-session", "-d", "-s", "drill", "-x", "200", "-y", "50",
                    "-c", str(drill_place["folder"]), command, env=env)
    assert started.returncode == 0, started.stderr
    try:
        seen = _wait_for(socket, (*STARTUP_MARKERS, *NOT_FOUND_MARKERS, LAST_PROMPT, EXIT_MARK), WAIT_S)
        text = _pane(socket)
        if seen in STARTUP_MARKERS:
            pytest.skip(f"the pane shows a startup screen ({seen!r}); the drill never answers it")
        assert seen == LAST_PROMPT, f"resume did not show the last prompt (saw {seen!r}):\n{text[-2000:]}"
        _tmux(socket, "send-keys", "-t", "drill", "-l", "/exit")
        time.sleep(POLL_S)
        _tmux(socket, "send-keys", "-t", "drill", "Enter")
        assert _wait_for(socket, (EXIT_MARK,), EXIT_WAIT_S) == EXIT_MARK, _pane(socket)[-2000:]
    finally:
        _tmux(socket, "kill-server")
