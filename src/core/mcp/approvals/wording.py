
from __future__ import annotations

from typing import Any, Callable, Dict

from src.core.automations.models import SYSTEM_ACTIONS
from src.core.mcp.approvals import diff as approval_diff

MAX_QUOTED = 80


def quoted(value: Any) -> str:
    text = str(value if value is not None else "")
    if len(text) > MAX_QUOTED:
        text = text[: MAX_QUOTED - 3] + "..."
    return f"'{text}'"


def _send_keys(args: Dict[str, Any], target: str, summary: str) -> str:
    parts = [quoted(args["text"])] if args.get("text") else []
    parts += [str(k) for k in args.get("keys") or []]
    return f"type {' + '.join(parts) or 'nothing'} into {target}"


def _restart(args: Dict[str, Any], target: str, summary: str) -> str:
    if args.get("pane_live"):
        return f"restart {target}: this stops the running agent and resumes its conversation"
    return f"restart {target} (its agent has exited) and resume its conversation"


def _crosstalk(args: Dict[str, Any], target: str, summary: str) -> str:
    return f"send {target} a first message: {quoted(args.get('text', ''))}"


def _resume(args: Dict[str, Any], target: str, summary: str) -> str:
    return f"resume the paused agent conversation with {target} and send {quoted(args.get('text', ''))}"


def _target_phrase(target: Any) -> str:
    if not isinstance(target, dict):
        return "runs its target"
    kind = target.get("kind")
    if kind == "agent":
        level = {"edits_in_folder": "can edit files in its folder", "unattended": "UNATTENDED with no permission prompts"}.get(
            target.get("permission"), "read only")
        return (f"runs a claude agent in {quoted(target.get('folder', ''))} as login {target.get('login_account_id') or 'the default'}, "
                f"model {target.get('model') or 'default'}, {level}, up to ${target.get('max_budget_usd', 1.0)} and {target.get('max_turns', 30)} turns")
    if kind == "recipe":
        name = target.get("recipe")
        return f"runs the system action {name}" if name in SYSTEM_ACTIONS else f"runs the {name} report"
    if kind == "command":
        return f"runs the allowed command {quoted(target.get('command', ''))}"
    if kind == "sequence":
        return "runs in order: " + "; then ".join(_target_phrase(step) for step in target.get("steps") or ())
    if kind == "session_message":
        return f"sends a message to session {quoted(target.get('session_uuid', ''))}"
    if kind == "blueprint_launch":
        return f"launches blueprint {quoted(target.get('blueprint_uuid', ''))}"
    if kind == "swarm_card":
        return f"deals a swarm card {quoted(target.get('title', ''))}"
    return "runs its target"


def _with_diff(sentence: str, args: Dict[str, Any]) -> str:
    listed = approval_diff.markdown(args.get("diff"))
    return f"{sentence}\n\n{listed}" if listed else sentence


def _automation_create(args: Dict[str, Any], target: str, summary: str) -> str:
    return _with_diff(f"create automation {quoted(args.get('name', ''))}: cron {quoted(args.get('cron', ''))}, "
                      f"{_target_phrase(args.get('target'))}", args)


def _automation_update(args: Dict[str, Any], target: str, summary: str) -> str:
    fields = sorted(k for k in args if k not in ("automation_id", "revision", "automation", "diff"))
    who = quoted(args["automation"]) if args.get("automation") else args.get("automation_id", "")
    sentence = f"edit automation {who}: change {', '.join(fields)}"
    if isinstance(args.get("target"), dict):
        sentence = f"{sentence}; it then {_target_phrase(args['target'])}"
    return _with_diff(sentence, args)


def _automation_delete(args: Dict[str, Any], target: str, summary: str) -> str:
    who = quoted(args["automation"]) if args.get("automation") else args.get("automation_id", "")
    return _with_diff(f"delete automation {who} and its run history", args)


_TARGETLESS = frozenset({"automation_create", "automation_update", "automation_delete"})

_RULES: Dict[str, Callable[[Dict[str, Any], str, str], str]] = {
    "session_send_keys": _send_keys,
    "session_restart": _restart,
    "session_stop": lambda args, target, summary: f"stop {target} (it sleeps; its row and conversation stay)",
    "session_delete": lambda args, target, summary: f"DELETE {target}: its tmux session is killed",
    "crosstalk_send": _crosstalk,
    "crosstalk_resume": _resume,
    "automation_create": _automation_create,
    "automation_update": _automation_update,
    "automation_delete": _automation_delete,
}


def plain(action: str, args: Dict[str, Any], target_name: str, summary: str) -> str:
    rule = _RULES.get(action)
    if rule is None or (not target_name and action not in _TARGETLESS):
        return summary or action.replace("_", " ")
    try:
        return rule(args, target_name, summary)
    except (KeyError, TypeError, AttributeError):
        return summary or action.replace("_", " ")
