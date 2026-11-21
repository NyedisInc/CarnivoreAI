
from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional

from src.core.mcp import in_use as in_use_mod

DANGER = "danger"
CONFIRM = "confirm"

_DESTRUCTIVE_SUFFIXES = ("_delete", "_purge", "_remove", "_kill")

_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')

Consequence = Dict[str, Any]
Detail = Dict[str, str]


def short_path(path: Any) -> str:
    if not isinstance(path, str) or not path:
        return ""
    home = os.path.expanduser("~")
    if home and home != "~" and (path == home or path.startswith(home.rstrip("/") + "/")):
        return "~" + path[len(home.rstrip("/")):]
    return path


def quoted_names(summary: str) -> List[str]:
    out: List[str] = []
    for match in _QUOTED.findall(summary or ""):
        try:
            value = json.loads(match)
        except ValueError:
            continue
        if isinstance(value, str):
            out.append(value)
    return out


def _c(key: str, **params: Any) -> Consequence:
    return {"key": key, "params": {k: str(v) for k, v in params.items()}}


def _first_line(text: str) -> str:
    return (text or "").split("\n", 1)[0].strip()


class _Ctx:

    def __init__(self, action: str, args: Dict[str, Any], target: str, summary: str, plain: str,
                 confirm_text: str, live: bool) -> None:
        self.action, self.args, self.target = action, args or {}, target
        self.summary, self.plain, self.confirm_text, self.live = summary or "", plain or "", confirm_text, live
        self.names = quoted_names(self.summary)

    def name(self, index: int = 0) -> str:
        return self.names[index] if len(self.names) > index else ""


Rule = Callable[[_Ctx], tuple]


def _purge(ctx: _Ctx) -> tuple:
    detail = [{"key": "fingerprint", "value": str(ctx.args.get("plan_fingerprint") or "")}]
    return ("purge", "session", ctx.confirm_text or ctx.target, DANGER,
            [_c("purge_gone"), _c("cannot_undo")], detail)


def _delete_session(ctx: _Ctx) -> tuple:
    cons = [_c("session_killed"), _c("record_leaves")] if ctx.live else [_c("nothing_running"), _c("record_leaves")]
    return ("delete", "session", ctx.target, DANGER, cons, [])


def _restart(ctx: _Ctx) -> tuple:
    if ctx.args.get("pane_live"):
        return ("restart", "session", ctx.target, DANGER, [_c("agent_stops"), _c("conversation_resumes")], [])
    return ("restart", "session", ctx.target, CONFIRM, [_c("conversation_resumes")], [])


def _move(ctx: _Ctx) -> tuple:
    root = ctx.args.get("new_root") or ""
    how = _c("folder_renamed") if ctx.args.get("move_folder") else _c("folder_repointed")
    detail = [{"key": "new_root", "value": str(root)},
              {"key": "fingerprint", "value": str(ctx.args.get("plan_fingerprint") or "")}]
    return ("move", "project", ctx.name(0), CONFIRM, [_c("moves_to", to=short_path(root)), how, _c("sessions_follow")],
            detail)


def _pack(ctx: _Ctx) -> tuple:
    only = [str(x) for x in ctx.args.get("local_only") or []]
    cons = [_c("pack_in_place"), _c("originals_to_trash")]
    detail = [{"key": "fingerprint", "value": str(ctx.args.get("plan_fingerprint") or "")}]
    if ctx.args.get("accept_local_only") and only:
        cons.append(_c("pack_only_copy", repos=len(only)))
        detail.insert(0, {"key": "only_copy", "value": "; ".join(only)})
        return ("pack", "project", ctx.name(0), DANGER, cons, detail)
    return ("pack", "project", ctx.name(0), CONFIRM, cons, detail)


def _unpack(ctx: _Ctx) -> tuple:
    warning = str(ctx.args.get("integrity_warning") or "")
    cons = [_c("unpack_restores"), _c("archive_to_trash")]
    detail = [{"key": "fingerprint", "value": str(ctx.args.get("plan_fingerprint") or "")}]
    if warning:
        cons.append(_c("archive_modified"))
        detail.insert(0, {"key": "archive_warning", "value": warning})
        return ("unpack", "project", ctx.name(0), DANGER, cons, detail)
    return ("unpack", "project", ctx.name(0), CONFIRM, cons, detail)


def _create_project(ctx: _Ctx) -> tuple:
    path = ctx.args.get("path") or ""
    return ("create", "project", str(ctx.args.get("name") or ctx.name(0)), CONFIRM,
            [_c("in_folder", path=short_path(path))], [{"key": "path", "value": str(path)}])


def _company_create(ctx: _Ctx) -> tuple:
    where = _c("under_company", company=ctx.name(1)) if ctx.args.get("parent_id") is not None else _c("top_level")
    return ("create", "company", str(ctx.args.get("name") or ctx.name(0)), CONFIRM, [where], [])


def _named(verb: str, obj: str, tone: str, *cons: Consequence) -> Rule:
    return lambda ctx: (verb, obj, ctx.name(0), tone, list(cons), [])


def _session(verb: str, tone: str, *cons: Consequence) -> Rule:
    return lambda ctx: (verb, "session", ctx.target, tone, list(cons), [])


def _renamed(obj: str) -> Rule:
    return lambda ctx: ("rename", obj, ctx.name(0), CONFIRM,
                        [_c("new_name", name=str(ctx.args.get("name") or ctx.name(1))), _c("folder_untouched")], [])


def _company_parent(ctx: _Ctx) -> tuple:
    where = _c("top_level") if ctx.args.get("parent_id") is None else _c("under_company", company=ctx.name(1))
    return ("move", "company", ctx.name(0), CONFIRM, [where, _c("companies_follow")], [])


def _company_hq(ctx: _Ctx) -> tuple:
    if ctx.args.get("project_id") is None:
        return ("clear", "company_home_project", ctx.name(0), CONFIRM, [_c("home_cleared"), _c("folder_untouched")], [])
    return ("set", "company_home_project", ctx.name(1), CONFIRM,
            [_c("home_set", project=ctx.name(0)), _c("folder_untouched")], [])


def _dialog_answer(ctx: _Ctx) -> tuple:
    choice = ctx.args.get("choice") or {}
    kind = next(iter(choice), "")
    value = choice.get(kind)
    if isinstance(value, list):
        picked = ", ".join(str(v) for v in value)
    elif kind in ("option", "other") and value:
        picked = _cut(_no_breaks(str(value)), _PICKS_MAX)
    else:
        picked = ""
    cons = [_c("answers_with", choice=picked)] if picked else [_c("answers_other")]
    return ("answer", "session_dialog", ctx.target, CONFIRM, cons + [_c("agent_continues")], [])


_PICK_MAX = 60
_PICKS_MAX = 480


def _cut(text: Any, limit: Optional[int] = _PICK_MAX) -> str:
    text = str(text)
    return text if limit is None or len(text) <= limit else text[:limit] + "..."


def _no_breaks(text: str) -> str:
    return "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text)


_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b.?")


def _plain_text(text: str) -> str:
    return "".join(c for c in _ESCAPES.sub("", text) if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf", "Zl", "Zp"))


def _question_pick(answer: Any, limit: Optional[int] = _PICK_MAX) -> str:
    answer = answer if isinstance(answer, dict) else {}
    picked = answer.get("options") if isinstance(answer.get("options"), list) else [answer.get("option")]
    flat = (lambda v: " ".join(v.split())) if limit is not None else _no_breaks
    parts = [_cut(flat(v), limit) for v in picked if v is not None]
    if answer.get("other") is not None:
        parts.append(f'typed text "{_cut(flat(answer["other"]), limit)}"')
    if answer.get("notes") is not None:
        parts.append(f'notes "{_cut(flat(answer["notes"]), limit)}"')
    return ", ".join(parts)


def _dialog_questions_answer(ctx: _Ctx) -> tuple:
    answers = ctx.args.get("answers") or []
    lines = [f"{i + 1}. {_question_pick(a) or 'left unanswered'}" for i, a in enumerate(answers)]
    picks = "; ".join(lines)
    if len(picks) > _PICKS_MAX:
        kept = 1
        while kept < len(lines) and len("; ".join(lines[:kept + 1])) <= _PICKS_MAX:
            kept += 1
        more = f"; ... and {len(lines) - kept} more" if kept < len(lines) else ""
        picks = "; ".join(lines[:kept])[:_PICKS_MAX] + ("..." if len(lines[0]) > _PICKS_MAX and kept == 1 else "") + more
    return ("answer", "session_dialog", ctx.target, CONFIRM,
            [_c("answers_all", count=len(answers), picks=picks), _c("agent_continues")],
            [{"key": "answer", "value": f"{i + 1}. {_question_pick(a, None) or 'left unanswered'}"} for i, a in enumerate(answers)])


def _plugin_session(ctx: _Ctx) -> tuple:
    a = ctx.args
    skips, unchecked = a.get("skips_permissions") is True, a.get("unchecked") is True
    line = "plugin_agent_skips" if skips else "plugin_agent_custom" if unchecked else "plugin_agent"
    agent = _c(line, agent=a.get("agent_type", ""), profile=a.get("profile_label", ""),
               badge=a.get("badge", ""))
    prompt = str(a.get("prompt") or "")
    return ("start", "session", str(a.get("plugin", "")), DANGER if skips or unchecked else CONFIRM,
            [_c("plugin_project", project=a.get("project", ""), where=a.get("where", "")), agent,
             _c("plugin_prompt", prompt=json.dumps(prompt)) if prompt else _c("plugin_no_prompt")], [])


_MODE_WORDS = {"default": "ask", "manual": "ask", "plan": "ask", "ask": "ask", "acceptEdits": "edits", "auto": "auto",
               "dontAsk": "dontask", "bypassPermissions": "bypass", "skip_all": "bypass", "unknown": "unknown"}


def _delegate(ctx: _Ctx) -> tuple:
    a = ctx.args
    computer, folder = str(a["computer"]), str(a["folder"])
    copy = _c("delegate_copy", folder=short_path(folder))
    tools = [str(t) for t in a.get("installs") or []]
    install = [_c("delegate_installs", tools=", ".join(tools), computer=computer)] if tools else []
    if "task" not in a:
        command = str(a["command"])
        runs = "delegate_runs_ssh" if a.get("ssh") is True else "delegate_runs"
        return ("run", "job", computer, CONFIRM, [_c(runs, command=_cut(command, 60), computer=computer), *install, copy],
                [{"key": "command", "value": command}, {"key": "path", "value": folder}])
    task, agent = str(a["task"]), str(a.get("agent_type") or "")
    word = _MODE_WORDS.get(str(a.get("permission_mode") or "unknown"), "unknown")
    definition = a.get("definition") or {}
    prompt, file = _plain_text(str(definition.get("prompt") or "")), _no_breaks(str(definition.get("file") or ""))
    return ("run", "job", computer, CONFIRM,
            [_c("delegate_agent_runs", agent=agent or "an agent", computer=computer, task=_cut(_no_breaks(task), 100)), *install, copy,
             _c(f"delegate_mode_{word}", computer=computer)],
            [{"key": "task", "value": task}, {"key": "agent_type", "value": agent},
             {"key": "definition", "value": prompt, "file": file}, {"key": "family", "value": str(a.get("family") or "")},
             {"key": "path", "value": folder}, {"key": "model", "value": str(a.get("model") or "")},
             {"key": "time_cap", "value": str(a["time_cap_minutes"]) if a.get("time_cap_minutes") else ""}])


_POSTURE_KEYS = {"ask": "place_mode_ask", "accept_edits": "place_mode_edits", "skip_all": "delegate_mode_bypass", "unknown": "place_mode_unknown"}


def _placed_create(ctx: _Ctx) -> tuple:
    a = ctx.args
    if a.get("placement") != "auto":
        return _fallback(ctx)
    computer, reason = str(a["computer"]), str(a["reason"])
    if "posture" not in a:
        return (ctx.action.replace("_", " "), "", ctx.target or ctx.name(0), CONFIRM, [_c("place_here", reason=reason)], [])
    account = str(a.get("account") or "")
    cons = [_c("place_remote", computer=computer, reason=reason),
            _c("place_account", account=account, computer=computer) if account else _c("place_account_default", computer=computer),
            _c(_POSTURE_KEYS.get(str(a["posture"]), "place_mode_unknown"), computer=computer)]
    return (ctx.action.replace("_", " "), "", ctx.target or ctx.name(0), DANGER if a["posture"] == "skip_all" else CONFIRM, cons, [])


_RULES: Dict[str, Rule] = {
    "delegate": _delegate,
    "session_create": _placed_create,
    "agent_spawn": _placed_create,
    "plugin_session_create": _plugin_session,
    "session_purge": _purge,
    "session_delete": _delete_session,
    "session_restart": _restart,
    "session_stop": _session("stop", CONFIRM, _c("sleeps"), _c("conversation_kept")),
    "session_wake": _session("wake", CONFIRM, _c("wakes")),
    "project_move": _move,
    "project_pack": _pack,
    "project_unpack": _unpack,
    "project_create": _create_project,
    "project_rename": _renamed("project"),
    "project_archive": _named("archive", "project", CONFIRM, _c("list_only"), _c("folder_untouched")),
    "project_unarchive": _named("restore", "project", CONFIRM, _c("list_only"), _c("folder_untouched")),
    "project_delete": _named("delete", "project", DANGER, _c("project_deleted"), _c("folder_kept"), _c("cannot_undo")),
    "company_create": _company_create,
    "company_rename": _renamed("company"),
    "company_parent_set": _company_parent,
    "company_hq_set": _company_hq,
    "session_dialog_answer": _dialog_answer,
    "session_dialog_questions_answer": _dialog_questions_answer,
    "company_delete": _named("delete", "company", DANGER, _c("company_deleted"), _c("folder_untouched")),
}


def _fallback(ctx: _Ctx) -> tuple:
    tone = DANGER if ctx.action.endswith(_DESTRUCTIVE_SUFFIXES) else CONFIRM
    words = _first_line(ctx.plain) or ctx.summary
    cons = [_c("summary", text=words)] if words else []
    return (ctx.action.replace("_", " "), "", ctx.target or ctx.name(0), tone, cons, [])


def build(action: str, args: Optional[Dict[str, Any]], target_name: str, summary: str, plain: str = "",
          confirm_text: str = "", live: bool = False,
          in_use: Optional[Dict[str, Any]] = None, beast_hint: bool = False) -> Dict[str, Any]:
    ctx = _Ctx(action, args or {}, target_name or "", summary, plain, confirm_text, live)
    rule = _RULES.get(action, _fallback)
    try:
        verb, obj, name, tone, cons, detail = rule(ctx)
    except (KeyError, TypeError, AttributeError, ValueError):
        verb, obj, name, tone, cons, detail = _fallback(ctx)
    detail = [row for row in detail if row["value"]]
    if summary:
        detail.append({"key": "summary", "value": summary})
    card = {"verb": verb, "object": obj, "name": name or "", "tone": tone,
            "consequences": cons[:4 if action == "delegate" else 3], "detail": detail}
    if beast_hint and action == "delegate":
        card["beast_hint"] = True
    block = in_use_mod.display_parts(in_use)
    if block:
        card["in_use"] = block
    return card

