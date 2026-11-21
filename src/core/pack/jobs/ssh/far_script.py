
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from src.core.hosts.ssh_exec import SshArgumentError, posix_quote
from src.core.pack.jobs.types import JobError



class FarScriptError(JobError):

    def __init__(self, detail: str) -> None:
        super().__init__("bad_request", detail, 422)


_HERE = Path(__file__).resolve().parent
MAX_ANSWER = 64 * 1024
MAX_FIELD = 256
MAX_BODY = 1024 * 1024
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")

VERBS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "hello": ((), ("root",)),
    "probe": ((), ("root",)),
    "pressure": ((), ("root",)),
    "claim": (("uid", "name", "job"), ("root", "slots")),
    "start": (("uid", "name", "job", "slot", "commit", "cap"), ("root", "blob", "caller", "est", "memo")),
    "status": (("job",), ("root",)),
    "collect": (("job",), ("root",)),
    "stop": (("job",), ("root",)),
    "release": (("job",), ("root", "keep")),
    "sweep": ((), ("root",)),
    "forget": (("uid", "name"), ("root",)),
    "seal": (("blob", "size", "sha256"), ("root",)),
}
_TOKENS: Dict[str, "re.Pattern[str]"] = {
    "uid": re.compile(r"^[A-Za-z0-9_-]{8,64}$"),
    "name": re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,47}$"),
    "job": re.compile(r"^[A-Za-z0-9_-]{8,64}$"),
    "slot": re.compile(r"^[1-9]$"),
    "slots": re.compile(r"^[1-9]$"),
    "commit": re.compile(r"^[0-9a-f]{40}$"),
    "blob": re.compile(r"^[0-9a-f]{8,64}$"),
    "cap": re.compile(r"^[0-9]{1,6}$"),
    "caller": re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$"),
    "est": re.compile(r"^[0-9]{1,6}$"),
    "size": re.compile(r"^[0-9]{1,12}$"),
    "sha256": re.compile(r"^[0-9a-f]{64}$"),
    "keep": re.compile(r"^[01]$"),
}
_QUOTED = {"root": 512, "memo": 256}


def new_nonce() -> str:
    return secrets.token_hex(16)


def _read(name: str) -> str:
    text = (_HERE / name).read_text(encoding="utf-8")
    if not text.strip():
        raise FarScriptError(f"{name} is empty")
    return text


def _value(name: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise FarScriptError(f"{name} must be a string")
    if name in _QUOTED:
        if len(raw) > _QUOTED[name] or _CONTROL.search(raw) or "\n" in raw:
            raise FarScriptError(f"{name} is too long or holds control characters")
        if name == "root" and not raw.startswith("/"):
            raise FarScriptError("root must be an absolute path")
        if name == "root" and ".." in raw.split("/"):
            raise FarScriptError("root may not hold a .. part")
        try:
            return posix_quote(raw)
        except SshArgumentError as exc:
            raise FarScriptError(f"{name} cannot be quoted") from exc
    if not _TOKENS[name].fullmatch(raw):
        raise FarScriptError(f"{name} is not a valid token")
    return posix_quote(raw)


def _heredoc(var: str, content: str) -> str:
    if "\0" in content:
        raise FarScriptError(f"{var} holds a NUL byte")
    if len(content.encode("utf-8")) > MAX_BODY:
        raise FarScriptError(f"{var} is too large")
    try:
        return f"{var}={posix_quote(content)}\n"
    except SshArgumentError as exc:
        raise FarScriptError(f"{var} cannot be quoted") from exc


def render(verb: str, values: Mapping[str, str], *, command: Optional[str] = None, env_sh: Optional[str] = None,
           steps_sh: Optional[str] = None, nonce: str) -> bytes:
    if verb not in VERBS:
        raise FarScriptError("unknown verb")
    if not _NONCE.fullmatch(nonce):
        raise FarScriptError("bad nonce")
    required, optional = VERBS[verb]
    extra = set(values) - set(required) - set(optional)
    if extra or any(name not in values for name in required):
        raise FarScriptError("values do not match the verb")
    if verb != "start" and any(x is not None for x in (command, env_sh, steps_sh)):
        raise FarScriptError("only start takes a command")
    if verb == "start" and command is None:
        raise FarScriptError("start needs a command")
    head = ["set -eu\n", "umask 077\n", "LC_ALL=C; LANG=C; export LC_ALL LANG\n", f"CVJ_NONCE='{nonce}'\n", f"CVJ_VERB='{verb}'\n"]
    head += [f"CVJ_{name.upper()}={_value(name, values[name])}\n" for name in sorted(values)]
    if verb == "start":
        head.append(_heredoc("CVJ_COMMAND", command or ""))
        head.append(_heredoc("CVJ_ENV_SH", env_sh or ""))
        head.append(_heredoc("CVJ_STEPS_SH", steps_sh or ""))
        head.append(_heredoc("CVJ_RUN_SH", _read("run.sh")))
    return ("".join(head) + _read("driver.sh")).encode("utf-8")


@dataclass
class FarAnswer:

    rc: int
    fields: Dict[str, str] = field(default_factory=dict)
    lines: List[str] = field(default_factory=list)

    def all(self, key: str) -> List[str]:
        return [line[len(key) + 1:] for line in self.lines if line == key or line.startswith(key + " ")]

    @property
    def error(self) -> Optional[Tuple[str, str]]:
        text = self.fields.get("error")
        if text is None:
            return None
        code, _sp, detail = text.partition(" ")
        return code, detail


def parse(stdout: bytes, nonce: str) -> FarAnswer:
    if len(stdout) > MAX_ANSWER:
        raise JobError("far_garbled", "the answer from the computer over ssh is too large", 502)
    marker = f"CVJ{nonce} "
    answer = FarAnswer(rc=-1)
    ended = False
    for raw in stdout.decode("utf-8", errors="replace").split("\n"):
        if not raw.startswith(marker):
            continue
        key, _sp, value = _CONTROL.sub("", raw[len(marker):].replace("\r", "")).partition(" ")
        key, value = key[:32], value[:MAX_FIELD]
        line = f"{key} {value}" if value else key
        if ended:
            raise JobError("far_garbled", "the computer over ssh kept talking after its end line", 502)
        if key == "end":
            try:
                answer.rc, ended = int(value), True
            except ValueError:
                raise JobError("far_garbled", "the end line from the computer over ssh is not a number", 502) from None
            continue
        answer.lines.append(line)
        answer.fields[key] = value
    if not ended:
        raise JobError("far_garbled", "the answer from the computer over ssh has no end line", 502)
    return answer
