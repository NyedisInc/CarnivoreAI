#!/usr/bin/env python3

import json
import os
import shlex
import sys
import urllib.request

EXEMPT = frozenset({
    "git", "gh", "ls", "cat", "head", "tail", "grep", "rg", "sed", "awk", "wc", "echo", "cd", "pwd", "mkdir", "mv", "cp", "rm",
    "touch", "find", "which", "cut", "tr", "sort", "uniq", "seq", "xargs", "tee", "export", "set", "unset", "local", "break",
    "continue", "return", "basename", "dirname", "realpath", "stat", "date", "shasum", "sha256sum", "md5", "jq", "yq", "printf",
    "read", "sysctl", "sw_vers", "uname", "ps", "pgrep", "lsof", "env", "id", "whoami", "pbcopy", "pbpaste", "open", "chmod",
    "chown", "ln", "readlink", "mktemp", "gofmt",
    "ssh", "scp", "sftp", "rsync", "mosh", "sleep", "true", "false", "test", "[", "[[",
})
FLOW_WORDS = frozenset({"until", "while", "do", "done", "if", "then", "else", "elif", "fi"})
LOCAL_HOSTS = ("localhost", "127.0.0.1")
SKIP_SUBAGENT_TYPES = frozenset({"image-generator"})
MARK = "///"
TIMEOUT_S = 0.25
_OPERATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "\n"}


def _unwrap_words(words):
    while words:
        head = words[0]
        if "=" in head and not head.startswith("=") and head.split("=", 1)[0].replace("_", "a").isalnum():
            words = words[1:]
            continue
        if head in FLOW_WORDS:
            words = words[1:]
            continue
        base = os.path.basename(head)
        if base in ("timeout", "gtimeout"):
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                flag = rest[0]
                rest = rest[2:] if flag in ("-k", "-s", "--kill-after", "--signal") and len(rest) > 1 else rest[1:]
            words = rest[1:] if len(rest) >= 2 else []
            continue
        if base in ("time", "nohup", "command", "exec"):
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            words = rest
            continue
        if base in ("nice", "caffeinate", "env"):
            rest = words[1:]
            while rest and (rest[0].startswith("-") or ("=" in rest[0] and base == "env")):
                flag = rest[0]
                rest = rest[2:] if flag in ("-n", "-u", "-t") and len(rest) > 1 else rest[1:]
            words = rest
            continue
        break
    return words


def _programs(command):
    command = command.split("<<", 1)[0]
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens, current = list(lexer), []
    out = []
    for token in tokens + [";"]:
        if token in _OPERATORS or (set(token) <= set(";&|()") and token):
            if current:
                out.append(current)
            current = []
        else:
            current.append(token)
    result = []
    for words in out:
        words = _unwrap_words(words)
        if not words or words[0] == "for":
            continue
        base = os.path.basename(words[0])
        if base in ("bash", "sh", "zsh") and len(words) >= 3 and words[1] in ("-c", "-lc", "-ec"):
            try:
                result.extend(_programs(words[2]))
                continue
            except ValueError:
                pass
        result.append((base, words[1:]))
    return result


def is_exempt(command):
    try:
        parts = _programs(command)
    except ValueError:
        return False
    if not parts:
        return True
    for name, args in parts:
        if name == "curl" and args and all(any(h in a for h in LOCAL_HOSTS) for a in args if "://" in a) and any("://" in a for a in args):
            continue
        if name not in EXEMPT:
            return False
    return True


def work_folder(command, cwd):
    try:
        parts = _programs(command)
    except ValueError:
        return cwd
    folder = cwd
    for name, args in parts:
        target = next((a for a in args if not a.startswith("-")), "") if name == "cd" else ""
        if target:
            folder = os.path.normpath(os.path.join(folder, os.path.expanduser(target)))
    return folder


def _env(name):
    return os.environ.get("CARNIVORE_" + name) or os.environ.get("CLOUDECODE_" + name) or ""


def ask(path, payload):
    url, token, session = _env("HOOK_URL"), _env("HOOK_TOKEN"), _env("SESSION_ID")
    if not (url and token and session and "/api/v1/" in url):
        return None
    base = url.split("/api/v1/", 1)[0]
    request = urllib.request.Request(
        base + "/api/v1/pack/jobs/" + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "X-Carnivore-Session": session,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _cwd_of(data):
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return cwd
    workspaces = data.get("workspacePaths")
    if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str) and workspaces[0].strip():
        return workspaces[0]
    return os.getcwd()


def _deny(reason):
    sys.stdout.write(json.dumps({"decision": "deny", "reason": f"{MARK} {reason}"}))
    return 0


def _allow(finished=False):
    sys.stdout.write("{}" if finished else json.dumps({"decision": "allow"}))
    return 0


def _handle_subagent(data, args, finished):
    if finished:
        return _allow(True)
    type_name = str(args.get("TypeName") or "").strip().lower()
    if type_name in SKIP_SUBAGENT_TYPES:
        return _allow(False)
    answer = ask("precheck/agent", {"folder": _cwd_of(data), "family": "agy"})
    if not answer or answer.get("decision") != "block":
        return _allow(False)
    where = answer.get("computer") or "another computer in the pack"
    return _deny(
        f"this computer is full and {where} has room. 1) call the carnivore delegate tool now with task = the subagent's prompt. "
        "2) if it answers here, start the subagent again: it goes through. 3) do not retry it first, wait, or schedule a wake."
    )


def _handle_command(data, tool_call, args, finished):
    command = args.get("CommandLine") or ""
    if not isinstance(command, str) or not command.strip() or args.get("IsDaemon") is True or is_exempt(command):
        return _allow(finished)
    use_id = str(tool_call.get("id") or "")
    if finished:
        if use_id:
            ask("precheck/finished", {"tool_use_id": use_id})
        return _allow(True)
    folder = work_folder(command, _cwd_of(data))
    answer = ask("precheck", {"command": command, "folder": folder, "tool_use_id": use_id, "background": False, "timeout_ms": None})
    if not answer or answer.get("decision") != "block":
        return _allow(False)
    where = answer.get("computer") or "another computer in the pack"
    return _deny(
        f"this computer is full and {where} has room. 1) call the carnivore delegate tool now with this exact command. "
        "2) if it answers here, run the command again: it goes through. 3) do not retry it first, wait, or schedule a wake."
    )


def main():
    finished = False
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return _allow(False)
        finished = data.get("hookEventName") == "PostToolUse"
        tool_call = data.get("toolCall") or {}
        if not isinstance(tool_call, dict):
            return _allow(finished)
        name = str(tool_call.get("name") or "")
        args = tool_call.get("args") or {}
        if not isinstance(args, dict):
            args = {}
    except Exception:  # noqa: BLE001
        return _allow(finished)
    if name == "invoke_subagent":
        return _handle_subagent(data, args, finished)
    if name == "run_command":
        return _handle_command(data, tool_call, args, finished)
    return _allow(finished)


if __name__ == "__main__":
    sys.exit(main())
