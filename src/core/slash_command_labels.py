
from typing import Any, Dict, List, Union

MAX_DESCRIPTION_LENGTH = 18

SHORT_DESCRIPTIONS: Dict[str, str] = {
    "/add-dir": "add a working dir",
    "/agents": "manage subagents",
    "/bug": "report a bug",
    "/clear": "wipe conversation",
    "/compact": "summarize history",
    "/config": "open settings",
    "/context": "show context usage",
    "/cost": "session cost",
    "/diff": "review changes",
    "/doctor": "check the install",
    "/effort": "set effort level",
    "/export": "export transcript",
    "/help": "list commands",
    "/hooks": "configure hooks",
    "/init": "write CLAUDE.md",
    "/login": "sign in",
    "/logout": "sign out",
    "/mcp": "manage mcp servers",
    "/memory": "edit memory files",
    "/model": "switch model",
    "/output-style": "set output style",
    "/permissions": "manage permissions",
    "/plan": "plan before edits",
    "/pr-comments": "read pr comments",
    "/privacy-settings": "privacy settings",
    "/release-notes": "what changed",
    "/resume": "reopen a session",
    "/review": "review a pr",
    "/rewind": "undo a checkpoint",
    "/security-review": "review for vulns",
    "/status": "account status",
    "/statusline": "set status line",
    "/tasks": "background tasks",
    "/terminal-setup": "install keybinding",
    "/todos": "list current todos",
    "/upgrade": "change plan",
    "/usage": "token and cost",
    "/vim": "vim editing mode",
}

DEFAULT_COMMON_COMMANDS: List[str] = [
    "/agents",
    "/clear",
    "/compact",
    "/context",
    "/hooks",
    "/mcp",
    "/resume",
    "/rewind",
    "/usage",
    "/login",
]

MIGRATION_APPENDED_COMMANDS: List[str] = [
    "/login",
]


def describe(command: str) -> str:
    if not isinstance(command, str):
        return ""
    key = command.strip()
    if not key:
        return ""
    if not key.startswith("/"):
        key = "/" + key
    return SHORT_DESCRIPTIONS.get(key, "")


def normalize(
    raw: Union[List[Any], None],
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for entry in raw or []:
        if isinstance(entry, str):
            command = entry.strip()
            description = describe(command)
        elif isinstance(entry, dict):
            command = str(entry.get("command", "")).strip()
            description = entry.get("description")
            if description is None:
                description = describe(command)
            description = str(description).strip()
        else:
            continue

        if not command:
            continue
        out.append({"command": command, "description": description})
    return out


def entry_command(entry: Any) -> str:
    if isinstance(entry, str):
        command = entry.strip()
    elif isinstance(entry, dict):
        command = str(entry.get("command", "")).strip()
    else:
        return ""
    if not command:
        return ""
    return command if command.startswith("/") else "/" + command


def append_missing_commands(raw: Any, commands: List[str]) -> List[Any]:
    existing = list(raw) if isinstance(raw, list) else []
    present = {entry_command(e) for e in existing}
    out = list(existing)
    for command in commands:
        key = command if command.startswith("/") else "/" + command
        if key not in present:
            out.append(key)
            present.add(key)
    return out


def storage_form(raw: Any) -> List[Any]:
    out: List[Any] = []
    for entry in raw if isinstance(raw, list) else []:
        command = entry_command(entry)
        if not command:
            continue
        if isinstance(entry, dict):
            description = entry.get("description")
            description = "" if description is None else str(description).strip()
        else:
            description = ""
        if description:
            out.append({"command": command, "description": description})
        else:
            out.append(command)
    return out


def commands_only(details: List[Dict[str, str]]) -> List[str]:
    return [d["command"] for d in details]
