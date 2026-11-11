
from __future__ import annotations

import unicodedata
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Tuple

from src.core.approvals.plain_answer import summarize
from src.core.notifications.cards.model import Ctx, Part, clip, clip_lines, say

LETTERS = "abcdefgh"


def _act(act_id: str, label: str = "") -> Tuple[str, str]:
    return act_id, label or say(f"notify.card.act.{act_id}")


def _open() -> List[Tuple[str, str]]:
    return [_act("open")]


def _session_target(c: Ctx, kind: str) -> Dict[str, Any]:
    return {"type": kind, "session": c.event.session_id or ""}


def _opts(d: Dict[str, Any]) -> List[List[str]]:
    desc = {r.get("label"): r.get("description") or "" for r in d.get("rows") or []}
    return [[LETTERS[i], clip(o, 60), clip(desc.get(o, ""), 120)] for i, o in enumerate((d.get("options") or [])[: len(LETTERS)])]


def _dialog_target(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "dialog", "session": d.get("session_id") or "", "fingerprint": d.get("fingerprint") or ""}


def yesno(c: Ctx) -> Part:
    d = c.dialog
    if not c.detail or not d or not (d.get("plain_yes") or d.get("plain_no")):
        return Part(card={"ask": clip(d.get("question"), 400)} if c.detail and d else {}, acts=_open())
    acts = [_act("yes"), _act("no")] + ([_act("reply", say("notify.card.act.answer"))] if d.get("has_other") else [])
    return Part(card={"ask": clip(d.get("question"), 400)}, acts=acts, target=_dialog_target(d), ask=True)


def choice(c: Ctx) -> Part:
    d = c.dialog
    if not c.detail or not d:
        return Part(acts=_open())
    opts, multi, qcount = _opts(d), bool(d.get("multi_select")), int(d.get("question_total") or 1)
    card: Dict[str, Any] = {"ask": clip(d.get("question"), 400), "opts": opts, "multi": multi, "qcount": qcount}
    if multi or qcount > 1 or not 1 <= len(opts) <= 4:
        return Part(card=card, acts=_open())
    labels = list(d.get("options") or [])[:4]
    acts = [(f"opt.{i + 1}", clip(lab, 40)) for i, lab in enumerate(labels)]
    if len(opts) <= 3 and d.get("has_other"):
        acts.append(_act("reply", say("notify.card.act.answer")))
    return Part(card=card, acts=acts, target=_dialog_target(d), ask=True)


def permission(c: Ctx) -> Part:
    d = c.dialog
    if not c.detail or not d:
        return Part(acts=_open())
    lines = clip_lines(d.get("body") or d.get("question"), 200, 300)
    card: Dict[str, Any] = {"cmd": lines[:12], "opts": _opts(d)}
    tool = c.hint.get("tool") or summarize(SimpleNamespace(**{k: d.get(k) or "" for k in ("family", "body", "question")}))[0].lower()
    for key, value in (("dir", c.hint.get("dir")), ("tool", tool)):
        if value:
            card[key] = clip(value, 120)
    options = list(d.get("options") or [])
    if not 1 <= len(options) <= 4:
        return Part(card=card, full={"cmd": lines}, acts=_open())
    acts = [(f"opt.{i + 1}", clip(o, 40)) for i, o in enumerate(options)]
    return Part(card=card, full={"cmd": lines}, acts=acts, target=_dialog_target(d), ask=True)


def _media(c: Ctx) -> Dict[str, Any]:
    return dict(c.hint.get("media") or {})


def _descriptor(m: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("id", "mime", "bytes", "w", "h", "dur")
    return {k: m[k] for k in keys if m.get(k) is not None}


def file(c: Ctx) -> Part:
    m = _media(c)
    card = {"name": clip(m.get("name"), 120), "bytes": m.get("bytes"), "mime": m.get("mime"), "from": c.agent}
    if m.get("pages"):
        card["pages"] = m["pages"]
    full: Dict[str, Any] = {"poster": True} if m.get("poster") else {}
    head = [clip(ln, 100) for ln in (m.get("head") or [])][:8] if c.detail else []
    if head:
        full["head"] = head
    return Part(card=card, full=full,
                acts=[_act("open_file"), _act("save_file")], media=_descriptor(m))


def image(c: Ctx) -> Part:
    m = _media(c)
    card = {"w": m.get("w"), "h": m.get("h"), "caption": clip(m.get("caption"), 120)}
    return Part(card={k: v for k, v in card.items() if v}, acts=[_act("open"), _act("save")], media=_descriptor(m))


def video(c: Ctx) -> Part:
    m = _media(c)
    card = {"dur": m.get("dur"), "w": m.get("w"), "h": m.get("h"), "caption": clip(m.get("caption"), 120)}
    return Part(card={k: v for k, v in card.items() if v}, acts=[_act("play"), _act("open")], media=_descriptor(m))


def _mixed_script(host: str) -> bool:
    for label in host.split("."):
        scripts = {unicodedata.name(ch, "?").split(" ")[0] for ch in label if ch.isalpha()}
        if len(scripts) > 1:
            return True
    return False


def link(c: Ctx) -> Part:
    url = str(c.hint.get("url") or "")
    host = url.split("://", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0]
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        ascii_host = host
    card: Dict[str, Any] = {"host": ascii_host, "url": clip(url, 2000), "mixed_script": _mixed_script(host)}
    if c.hint.get("title"):
        card["title"] = clip(c.hint["title"], 120)
    return Part(card=card, acts=[_act("open_link"), _act("copy_link")])


def finished(c: Ctx) -> Part:
    files = list(c.hint.get("files") or [])
    stats = [list(s)[:2] for s in (c.hint.get("stats") or [])][:3]
    card = {"mins": c.hint.get("mins"), "files": [clip(f, 80) for f in files[:3]], "nfiles": c.hint.get("nfiles", len(files)),
            "stats": stats if any(stats) else None}
    return Part(card={k: v for k, v in card.items() if v not in (None, [], 0)}, acts=[_act("open"), _act("reply")],
                target=_session_target(c, "send"))


def died(c: Ctx) -> Part:
    tail = [clip(ln, 100) for ln in (c.hint.get("tail") or [])][-6:] if c.detail else []
    card = {"tail": tail, "exit": c.hint.get("exit")}
    return Part(card={k: v for k, v in card.items() if v not in (None, [])}, acts=[_act("reopen"), _act("open")],
                target=_session_target(c, "reopen"))


SHOWN_SESSIONS = 6


def update(c: Ctx) -> Part:
    names = list(c.hint.get("sessions") or [])[:SHOWN_SESSIONS]
    card = {"from": c.hint.get("from"), "to": c.hint.get("to"), "sessions": names}
    target = {"type": "agent_update", "sessions": [str(i) for i in (c.hint.get("ids") or [])][:len(names)]}
    return Part(card={k: v for k, v in card.items() if v}, acts=[_act("restart_agents"), _act("later")], target=target)


def appupdate(c: Ctx) -> Part:
    card = {"from": c.hint.get("from"), "to": c.hint.get("to"), "notes": [clip(n, 90) for n in (c.hint.get("notes") or [])[:3]]}
    return Part(card={k: v for k, v in card.items() if v}, acts=[_act("install"), _act("later")], target={"type": "app_update"})


def swarm(c: Ctx) -> Part:
    h = c.hint
    if not c.detail:
        return Part(acts=_open())
    card = {"ask": clip(h.get("ask"), 300), "asker_path": clip(h.get("asker_path"), 80)}
    positions = [[clip(w, 40), clip(t, 200)] for w, t in (h.get("positions") or [])[:2]]
    acts: List[Tuple[str, str]] = _open()
    target = None
    if h.get("question_id") and len(positions) == 2:
        acts = [(f"pick.{i + 1}", clip(f"pick {p[0]}'s", 40)) for i, p in enumerate(positions)]
        acts.append(_act("answer"))
        target = {"type": "swarm", "question": str(h["question_id"])}
    return Part(card={k: v for k, v in card.items() if v}, full={"positions": positions} if positions else {}, acts=acts,
                target=target, ask=target is not None)


def crosstalk(c: Ctx) -> Part:
    text = clip(c.hint.get("text") or (c.event.details if c.detail else ""), 300)
    thread = [[clip(w, 40), clip(t, 160)] for w, t in (c.hint.get("thread") or [])][-3:] if c.detail else []
    return Part(card={"text": text} if text else {}, full={"thread": thread} if thread else {}, acts=[_act("reply")],
                target=_session_target(c, "send"))


def signin(c: Ctx) -> Part:
    card = {"account": c.hint.get("account"), "provider": c.hint.get("provider"), "reason": c.hint.get("reason"), "sessions": list(c.hint.get("sessions") or [])[:6]}
    return Part(card={k: v for k, v in card.items() if v}, acts=[_act("sign_in")])


def notice(c: Ctx) -> Part:
    body = clip(c.hint.get("body") or (c.event.details if c.detail else ""), 300)
    card = {"title": clip(c.event.title, 120), "body": body}
    return Part(card={k: v for k, v in card.items() if v}, acts=_open())


BUILDERS: Dict[str, Callable[[Ctx], Part]] = {
    "yesno": yesno, "choice": choice, "permission": permission, "file": file, "link": link, "image": image, "video": video,
    "finished": finished, "died": died, "update": update, "appupdate": appupdate, "swarm": swarm, "crosstalk": crosstalk,
    "signin": signin, "notice": notice,
}
