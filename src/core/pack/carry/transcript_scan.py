
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Dict, Iterator, List, Mapping, Optional

from src.core.claude_project_dirs import path_spellings
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.project_move.claude_side import transcript_roots

TICK_LIMIT_BYTES = 500 * 1024 * 1024
_MAX_ITEMS = 20
_SIZE_ENTRIES = 50_000
_SIZE_SECONDS = 3.0
_PATH_KEYS = ("file_path", "path", "notebook_path")
_DROPPED = (".carnivore", ".claude", ".ssh", ".aws", ".gnupg", ".config", ".cache", ".npm", ".docker", ".kube")
_SYSTEM = ("/tmp", "/private/tmp", "/var", "/private/var", "/opt", "/usr", "/bin", "/sbin", "/etc", "/private/etc", "/System", "/Library", "/dev", "/Applications")
_BASE_BINS = ("/bin/", "/usr/bin/", "/usr/sbin/", "/sbin/")
_SECRET = re.compile(r"((?:token|key|secret|password|passwd|auth)\w*=)\S+|\b[A-Za-z0-9_\-]{32,}\b", re.I)
_SERVER = re.compile(r"http\.server|runserver|uvicorn|gunicorn|flask run|npm (?:run )?(?:dev|start|serve)|vite|next dev|serve\b|live-server", re.I)
_PORT = (re.compile(r"http\.server\s+(\d{2,5})"), re.compile(r"(?:--port|--bind|-p|-l)[ =]+(?:[\w.]*:)?(\d{2,5})\b"),
         re.compile(r"\bPORT=(\d{2,5})\b"), re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})\b"))
_APP = re.compile(r"/Applications/([^/]+)\.app")
_SPLIT = re.compile(r"&&|\|\||[|;&\n]")


@dataclass
class TranscriptFindings:

    folders: List[Dict[str, Any]] = field(default_factory=list)
    tools: List[Dict[str, str]] = field(default_factory=list)
    servers: List[Dict[str, Any]] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)

    def view(self, can_carry_outside: bool) -> Dict[str, Any]:
        outside = [{**f, "carryable": can_carry_outside} for f in self.folders if f["kind"] == "outside"]
        return {"outside": outside, "other_projects": [f for f in self.folders if f["kind"] == "other_project"],
                "tools": [t for t in self.tools if t["status"] != "present"], "servers": self.servers}


def transcript_path(working_dir: str, claude_uuid: str) -> Optional[str]:
    for base in transcript_roots():
        for name in dict.fromkeys(slugify_project_dir(s) for s in path_spellings(working_dir)):
            candidate = os.path.join(str(base), name, f"{claude_uuid}.jsonl")
            if os.path.isfile(candidate) and not os.path.islink(candidate):
                return candidate
    return None


def tool_uses(lines: Iterator[str]) -> List[Dict[str, Any]]:
    uses: List[Dict[str, Any]] = []
    for line in lines:
        if "compact_boundary" in line and '"system"' in line:
            uses = []
            continue
        if '"tool_use"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        content = (record.get("message") or {}).get("content") if isinstance(record, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                uses.append({"name": str(block.get("name")), "input": block["input"]})
    return uses


def folder_size(path: str) -> Optional[int]:
    total, seen, deadline = 0, 0, time.monotonic() + _SIZE_SECONDS
    for here, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(here, d))]
        for name in names:
            seen += 1
            try:
                total += os.lstat(os.path.join(here, name)).st_size
            except OSError:
                continue
        if seen > _SIZE_ENTRIES or time.monotonic() > deadline:
            return None
    return total


def mask(command: str) -> str:
    return _SECRET.sub(lambda m: (m.group(1) + "***") if m.group(1) else "***", " ".join(command.split()))[:90]


def _tokens(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _paths_in(use: Dict[str, Any], home: str) -> List[str]:
    found = [str(use["input"][k]) for k in _PATH_KEYS if isinstance(use["input"].get(k), str)]
    if use["name"] == "Bash":
        for token in _tokens(str(use["input"].get("command", ""))):
            token = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            found.append(os.path.join(home, token[2:]) if token.startswith("~/") else token)
    return [p for p in found if p.startswith("/")]


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def _candidate(path: str) -> Optional[str]:
    path = os.path.realpath(path)
    if os.path.isdir(path):
        return path
    return os.path.dirname(path) if os.path.exists(path) else None


def _classify_folders(uses: List[Dict[str, Any]], root: str, covered: Collection[str], others: Mapping[str, str],
                      worktrees_of: Callable[[str], List[str]], home: str, found: TranscriptFindings) -> None:
    home = os.path.realpath(home)
    covered = [os.path.realpath(root), *(os.path.realpath(c) for c in covered)]
    candidates: List[str] = []
    for use in uses:
        for raw in _paths_in(use, home):
            folder = _candidate(raw)
            if folder is None or folder in (home, os.sep) or any(_under(folder, c) for c in covered):
                continue
            if any(_under(folder, os.path.join(home, d)) for d in _DROPPED):
                found.dropped.append(folder)
                continue
            if not _under(folder, home) and any(_under(folder, s) for s in _SYSTEM):
                continue
            candidates.append(folder)
    kept: List[str] = []
    for folder in sorted(set(candidates), key=len):
        if not any(_under(folder, k) for k in kept):
            kept.append(folder)
    owners: Dict[str, List[str]] = {}
    if kept and others:
        owners = {name: [os.path.realpath(r), *(os.path.realpath(w) for w in worktrees_of(r))] for name, r in others.items()}
    for folder in kept[:_MAX_ITEMS]:
        owner = next((n for n, bases in owners.items() if any(_under(folder, b) for b in bases)), None)
        if owner is not None:
            found.folders.append({"path": folder, "kind": "other_project", "project": owner})
            continue
        size = folder_size(folder)
        found.folders.append({"path": folder, "kind": "outside", "size": size, "tick": size is not None and size < TICK_LIMIT_BYTES})


def _command_words(command: str) -> List[str]:
    words = []
    for segment in _SPLIT.split(command):
        tokens = [t for t in _tokens(segment) if not re.match(r"^\w+=", t)]
        if tokens:
            words.append(os.path.basename(tokens[0]))
    return words


def _classify_tools(uses: List[Dict[str, Any]], toolchain: Optional[Mapping[str, Any]], found: TranscriptFindings) -> None:
    names: Dict[str, str] = {}
    for use in uses:
        if use["name"] != "Bash":
            continue
        command = str(use["input"].get("command", ""))
        for app in _APP.findall(command):
            names.setdefault(app, "unchecked")
        for word in _command_words(command):
            binary = shutil.which(word) if re.match(r"^[A-Za-z0-9._+-]{1,40}$", word) else None
            if binary is None or binary.startswith(_BASE_BINS):
                continue
            names.setdefault(word, "unchecked" if toolchain is None or word not in toolchain else ("present" if toolchain[word] else "missing"))
    found.tools = [{"name": n, "status": s} for n, s in sorted(names.items())][:_MAX_ITEMS]


def _classify_servers(uses: List[Dict[str, Any]], is_listening: Callable[[int], bool], found: TranscriptFindings) -> None:
    seen = set()
    for use in uses:
        command = str(use["input"].get("command", "")) if use["name"] == "Bash" else ""
        background = bool(use["input"].get("run_in_background")) or bool(re.search(r"&\s*$|\bnohup\b", command.strip()))
        port = next((int(m.group(1)) for rx in _PORT if (m := rx.search(command)) and int(m.group(1)) < 65536), None)
        if not (command and background and (port is not None or _SERVER.search(command))):
            continue
        if (port is not None and not is_listening(port)) or (port or command) in seen:
            continue
        seen.add(port or command)
        found.servers.append({"command": mask(command), **({"port": port} if port is not None else {})})
    found.servers = found.servers[-_MAX_ITEMS:]


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def scan_transcript(path: str, *, root: str, covered: Collection[str] = (), other_projects: Optional[Mapping[str, str]] = None,
                    worktrees_of: Callable[[str], List[str]] = lambda root: [], toolchain: Optional[Mapping[str, Any]] = None,
                    home: Optional[str] = None, is_listening: Callable[[int], bool] = _listening) -> TranscriptFindings:
    found = TranscriptFindings()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            uses = tool_uses(iter(handle))
    except OSError:
        return found
    _classify_folders(uses, root, covered, other_projects or {}, worktrees_of, home or os.path.expanduser("~"), found)
    _classify_tools(uses, toolchain, found)
    _classify_servers(uses, is_listening, found)
    return found
