
from __future__ import annotations

import re
import shlex
from typing import Any, FrozenSet, Mapping

NETWORK = "network"
FILE_DELETE = "file_delete"
SETTINGS_WRITE = "settings_write"
CREDENTIAL_ACCESS = "credential_access"

CATEGORIES = (NETWORK, FILE_DELETE, SETTINGS_WRITE, CREDENTIAL_ACCESS)

_NET_TOOLS = frozenset({"WebFetch", "WebSearch"})
_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

_B = r"(?:^|[\s;&|(`/])"
_NET_CMD = re.compile(
    _B + r"(?:curl|wget|nc|ncat|netcat|telnet|ssh|scp|sftp|ftp|rsync|dig|nslookup|osascript)\b"
    r"|https?://|\bgit\s+(?:push|fetch|clone|pull|ls-remote)\b|" + _B + r"gh\s"
    r"|\b(?:npm|pnpm|yarn|pip3?|brew|cargo|gem)\s+(?:install|add|i|publish)\b|\bopen\s+https?"
    r"|\b(?:urllib|urlopen|requests\.(?:get|post|put)|socket\.|http\.client|aiohttp|httpx|fetch\(|Net::HTTP)"
    r"|\bbase64\s+-[dD]\b[^\n]*\|\s*(?:ba|z)?sh\b")
_DELETE_CMD = re.compile(
    _B + r"(?<!git )(?:rm|rmdir|unlink|shred|trash|truncate)\b"
    r"|\bgit\s+(?:clean|reset\s+--hard|checkout\s+--)|\bfind\b[^\n]*\s-delete\b"
    r"|\bos\.(?:remove|unlink|rmdir)\b|\brmtree\b")
_SETTINGS_PATH = re.compile(
    r"(?:^|/)(?:settings(?:\.local)?\.json|\.claude\.json|config\.toml|managed-settings\.json|\.mcp\.json)$"
    r"|/\.claude/hooks/")
_SETTINGS_IN_CMD = re.compile(
    r"(?:settings(?:\.local)?\.json|managed-settings\.json|\.codex/config\.toml|\.mcp\.json|\.claude/hooks/)")
_WRITE_CMD = re.compile(r"(?:>>?|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\bln\b|\bpython3?\b|\bjq\b)")
_NOISE_REDIRECT = re.compile(r"\d?\s*>>?\s*/dev/null|\d?\s*>&\s*\d")
_CREDENTIAL = re.compile(
    r"\.credentials\.json|(?:^|/)auth\.json|\.claude\.json|(?:^|/)\.ssh(?:/|\b)|\.netrc"
    r"|\.aws/credentials|\.gnupg|id_(?:rsa|ed25519|ecdsa)\b|gh/hosts\.yml|\.git-credentials"
    r"|\.docker/config\.json|\.npmrc|\.pypirc|\.kube/config|(?:^|/)\.env(?:\.\w+)?\b|\bprintenv\b"
    r"|\bsecurity\s+(?:find|dump|export)-\w+|\bkeychain\b|\bgh\s+auth\s+token\b")


def _normalise(command: str) -> str:
    return command.replace('"', "").replace("'", "").replace("\\", "")


_PATTERN_COMMANDS = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack", "pgrep", "pkill"})
_SEGMENT_END = re.compile(r"^[;&|()]+$")
_PATTERN_OPTIONS = frozenset({"-e", "--regexp"})
_VALUE_OPTIONS = frozenset({"-m", "-A", "-B", "-C", "-g", "-t", "-T", "--include", "--exclude",
                            "--max-count", "--glob", "--type"})


def _drop_pattern_args(command: str) -> str:
    if not _PATTERN_COMMANDS.intersection(re.findall(r"[\w.-]+", command)):
        return command
    try:
        lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return command
    out: list = []
    active = False
    pattern_seen = False
    expect = ""
    at_start = True
    for token in tokens:
        if _SEGMENT_END.match(token):
            active, at_start, expect, pattern_seen = False, True, "", False
            out.append(token)
            continue
        if at_start:
            if "=" in token and not token.startswith("-") and "/" not in token.split("=", 1)[0]:
                out.append(token)
                continue
            at_start = False
            active = token.rsplit("/", 1)[-1] in _PATTERN_COMMANDS
            pattern_seen = False
            out.append(token)
            continue
        if not active:
            out.append(token)
            continue
        if expect:
            pattern_seen = pattern_seen or expect == "pattern"
            expect = ""
            continue
        if token.startswith("-") and len(token) > 1:
            name = token.split("=", 1)[0]
            has_value = "=" in token
            if name in _PATTERN_OPTIONS or (not token.startswith("--") and token.endswith("e")
                                            and name not in _VALUE_OPTIONS):
                if has_value:
                    pattern_seen = True
                    continue
                expect = "pattern"
                continue
            if name in _VALUE_OPTIONS and not has_value:
                expect = "value"
                continue
            if has_value and name in _VALUE_OPTIONS:
                continue
            out.append(token)
            continue
        if not pattern_seen:
            pattern_seen = True
            continue
        out.append(token)
    return " ".join(out)


def _text_of(tool_input: Mapping[str, Any]) -> str:
    parts = []
    for key in ("command", "file_path", "path", "notebook_path", "url"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(_normalise(value[:4096]))
    return "\n".join(parts)


def classify_call(name: str, tool_input: Any) -> FrozenSet[str]:
    data = tool_input if isinstance(tool_input, dict) else {}
    if name == "Bash":
        data = {**data, "command": _drop_pattern_args(str(data.get("command") or "")[:4096])}
    text = _text_of(data)
    found = set()
    if name in _NET_TOOLS or name.startswith("mcp__"):
        found.add(NETWORK)
    if name == "Bash":
        command = _normalise(str(data.get("command") or ""))
        if _NET_CMD.search(command):
            found.add(NETWORK)
        if _DELETE_CMD.search(command):
            found.add(FILE_DELETE)
        if _SETTINGS_IN_CMD.search(command) and _WRITE_CMD.search(_NOISE_REDIRECT.sub("", command)):
            found.add(SETTINGS_WRITE)
    if name in _WRITE_TOOLS:
        path = str(data.get("file_path") or data.get("notebook_path") or "")
        if _SETTINGS_PATH.search(path):
            found.add(SETTINGS_WRITE)
    if _CREDENTIAL.search(text):
        found.add(CREDENTIAL_ACCESS)
    return frozenset(found)
