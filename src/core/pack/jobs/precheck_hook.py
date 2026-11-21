#!/usr/bin/env python3

import json
import os
import shlex
import sys
import urllib.request

EXEMPT = frozenset({"git", "gh", "ls", "cat", "head", "tail", "grep", "rg", "sed", "awk", "wc", "echo", "cd", "pwd", "mkdir", "mv", "cp", "rm",
                    "touch", "find", "which"})
HEAVY_PROGRAMS = frozenset({"webpack", "tsc", "make", "xcodebuild", "gradle", "gradlew", "mvn", "pytest", "vitest", "jest", "playwright",
                            "ffmpeg", "blender", "remotion"})
HEAVY_ARGS = {"npm": {"build", "test"}, "pnpm": {"build", "test"}, "yarn": {"build", "test"}, "bun": {"build", "test"}, "vite": {"build"},
              "next": {"build"}, "cargo": {"build", "test"}, "go": {"build", "test"}, "swift": {"build", "test"}, "docker": {"build"}}
MARK = "///"
RED_MARK = "\x1b[31m///\x1b[0m"
LOCAL_HOSTS = ("localhost", "127.0.0.1")
TIMEOUT_S = 0.25
_OPERATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "\n"}


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
        while words and "=" in words[0] and not words[0].startswith("=") and words[0].split("=", 1)[0].replace("_", "a").isalnum():
            words = words[1:]
        if words:
            result.append((os.path.basename(words[0]), words[1:]))
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


def is_heavy(command):
    try:
        parts = _programs(command)
    except ValueError:
        return False
    for name, args in parts:
        if name in HEAVY_PROGRAMS or (name in HEAVY_ARGS and HEAVY_ARGS[name] & set(args)):
            return True
        if name in ("node", "bun") and any("build" in a for a in args):
            return True
    return False


def _seconds(text):
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        return float(text[:-1]) * scale[text[-1]] if text[-1] in scale else float(text)
    except (ValueError, IndexError):
        return 0.0


def expects_long(command, background=False, timeout_ms=None):
    if background is True or (isinstance(timeout_ms, (int, float)) and not isinstance(timeout_ms, bool) and timeout_ms > 120000):
        return True
    try:
        parts = _programs(command)
    except ValueError:
        return False
    for name, args in parts:
        if name in ("timeout", "gtimeout"):
            words = [a for a in args if not a.startswith("-")]
            if words and _seconds(words[0]) > 120:
                return True
    return False


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
    request = urllib.request.Request(base + "/api/v1/pack/jobs/" + path, data=json.dumps(payload).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                                                             "X-Carnivore-Session": session})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode())
    except Exception:  # noqa: BLE001
        return None


def message(text):
    return MARK + " " + text, RED_MARK + " " + text


def agent_task(tool, where):
    kind = tool.get("subagent_type")
    typed = ", agent_type = " + kind if isinstance(kind, str) and kind and all(c.islower() or c.isdigit() or c == "-" for c in kind) else ""
    return (f"this computer is full; carnivore runs this subagent on {where}, another computer in the pack. do not start it here: call the carnivore "
            f"delegate tool with task = the subagent's prompt{typed}, and use its answer.")


def main_agent(data):
    if data.get("hook_event_name") == "PostToolUse":
        return 0
    tool = data.get("tool_input") or {}
    answer = ask("precheck/agent", {"folder": data.get("cwd") or os.getcwd()})
    if not answer or answer.get("decision") != "block":
        return 0
    plain, terminal = message(agent_task(tool, answer.get("computer") or "another computer in the pack"))
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": plain},
                                 "systemMessage": terminal}) + "\n")
    return 0


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") in ("Agent", "Task"):
            return main_agent(data)
        tool = data.get("tool_input") or {}
        command = tool.get("command") or ""
        folder = work_folder(command, data.get("cwd") or os.getcwd())
        use_id = str(data.get("tool_use_id") or "")
        finished = data.get("hook_event_name") == "PostToolUse"
    except Exception:  # noqa: BLE001
        return 0
    if not command or is_exempt(command):
        return 0
    if finished:
        if use_id:
            ask("precheck/finished", {"tool_use_id": use_id})
        return 0
    answer = ask("precheck", {"command": command, "folder": folder, "tool_use_id": use_id, "background": tool.get("run_in_background") is True,
                              "timeout_ms": tool.get("timeout") if isinstance(tool.get("timeout"), int) else None})
    if not answer or answer.get("decision") != "block":
        return 0
    where = answer.get("computer") or "another computer in the pack"
    plain, terminal = message(f"this computer is full; carnivore runs this heavy command on {where}, another computer in the pack. "
                              "use the carnivore delegate tool.")
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": plain},
                                 "systemMessage": terminal}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
