#!/usr/bin/env python3

import json
import os
import sys
import urllib.request

TIMEOUT_S = 1.5
ALLOW = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def _env(name):
    return os.environ.get("CARNIVORE_" + name) or os.environ.get("CLOUDECODE_" + name) or ""


def ask(tool_name, tool_input, cwd):
    url, token, session = _env("HOOK_URL"), _env("HOOK_TOKEN"), _env("SESSION_ID")
    if not (url and token and session and "/api/v1/" in url):
        return None
    base = url.split("/api/v1/", 1)[0]
    body = json.dumps({"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}).encode()
    request = urllib.request.Request(base + "/api/v1/beast-mode/permission-request", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                                              "X-Carnivore-Session": session})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode())
    except Exception:  # noqa: BLE001
        return None


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name") or ""
        tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        cwd = data.get("cwd") or os.getcwd()
    except Exception:  # noqa: BLE001
        return 0
    answer = ask(tool_name, tool_input, cwd) if tool_name else None
    if isinstance(answer, dict) and answer.get("decision") == "allow":
        sys.stdout.write(json.dumps(ALLOW))
    return 0


if __name__ == "__main__":
    sys.exit(main())
