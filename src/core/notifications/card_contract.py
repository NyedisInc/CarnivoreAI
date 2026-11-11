
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.native_push.payload_crypto import MAX_PLAINTEXT_BYTES

PAYLOAD_VERSION = 2

KINDS: Tuple[str, ...] = (
    "yesno", "choice", "permission", "file", "link", "image", "video", "finished", "died", "update", "appupdate",
    "swarm", "crosstalk", "signin", "notice",
)

LEVELS: Dict[str, str] = {"p": "passive", "a": "active", "t": "time-sensitive"}
SOUNDS: Tuple[str, ...] = ("ask", "done", "alarm", "soft", "none", "default")
EARCONS: Tuple[str, ...] = ("ask", "done", "alarm", "soft")
SETTLE_WHERE: Tuple[str, ...] = ("computer", "phone", "auto", "elsewhere")

LIMITS: Dict[str, int] = {
    "title": 120, "body": 400, "path": 300, "thread": 200, "sub": 80, "cap": 43, "acts": 4, "act_label": 40,
    "card_bytes": 700, "body_trimmed": 200, "act_label_trimmed": 24, "card_full_bytes": 65536, "card_clip_lines": 12,
    "card_full_cmd_lines": 200,
}

PAYLOAD_KEYS: Tuple[str, ...] = (
    "title", "body", "path", "thread", "v", "sub", "kind", "type", "lv", "snd", "cap", "ttl", "acts", "card", "more", "media", "settle",
)
V1_KEYS: Tuple[str, ...] = ("title", "body", "path", "thread")
WEB_PUSH_KEYS: Tuple[str, ...] = V1_KEYS + ("tag",)


@dataclass(frozen=True)
class Action:

    id: str
    label_key: str
    face_id: bool = False
    text_input: bool = False
    foreground: bool = False


def _a(action_id: str, face_id: bool = False, text_input: bool = False, foreground: bool = False, label: str = "") -> Action:
    return Action(action_id, f"notify.card.act.{label or action_id}", face_id, text_input, foreground)


ACTIONS: Dict[str, Tuple[Action, ...]] = {
    "yesno": (_a("yes", True), _a("no", True), _a("reply", True, True)),
    "choice": (_a("opt.1", True), _a("opt.2", True), _a("opt.3", True), _a("reply", True, True)),
    "permission": (_a("opt.1", True), _a("opt.2", True), _a("opt.3", True), _a("opt.4", True)),
    "file": (_a("open_file", foreground=True), _a("save_file", foreground=True)),
    "link": (_a("open_link", foreground=True), _a("copy_link")),
    "image": (_a("open", foreground=True), _a("save", foreground=True)),
    "video": (_a("play"), _a("open", foreground=True)),
    "finished": (_a("open", foreground=True), _a("reply", True, True)),
    "died": (_a("reopen", True), _a("open", foreground=True)),
    "update": (_a("restart_agents", True), _a("later")),
    "appupdate": (_a("install", True), _a("later")),
    "swarm": (_a("pick.1", True), _a("pick.2", True), _a("answer", True, True)),
    "crosstalk": (_a("reply", True, True),),
    "signin": (_a("sign_in", foreground=True),),
    "notice": (_a("open", foreground=True),),
}
EFFECTS: Dict[str, str] = {
    "yesno": "deliver_answer via the dialog answer core (choice.plain, choice.option, or choice.other for reply)",
    "choice": "the same; opt.n resolves to the label stored with the capability, never one the phone sends",
    "permission": "the same, choice.option",
    "file": "none (the app opens or exports the media)", "link": "none (Safari opens it; copy happens in the card)",
    "image": "none", "video": "none (play is inline AVPlayer)", "finished": "reply: the send-message core",
    "died": "reopen: respawn_session on the dead-pane husk, no -k", "update": "the agent-update restart core",
    "appupdate": "the app-update install core", "swarm": "the swarm answer core", "crosstalk": "the send-message core",
    "signin": "none (opens the provider screen path)", "notice": "none",
}

ALL_CARD_FIELDS: Tuple[str, ...] = ("strip", "agent", "computer", "ts", "answered")
CARD_FIELDS: Dict[str, Tuple[str, ...]] = {
    "yesno": ("ask",), "choice": ("ask", "opts", "multi", "qcount"), "permission": ("cmd", "dir", "tool", "opts"),
    "file": ("name", "bytes", "mime", "from", "poster", "pages"), "link": ("host", "url", "title", "mixed_script"),
    "image": ("w", "h", "caption"), "video": ("dur", "w", "h", "caption"), "finished": ("mins", "files", "nfiles", "stats"),
    "died": ("tail", "exit"), "update": ("from", "to", "sessions"), "appupdate": ("from", "to", "notes"),
    "swarm": ("ask", "asker_path", "positions"), "crosstalk": ("text", "thread"), "signin": ("account", "provider", "reason", "sessions"),
    "notice": ("title", "body"),
}
FULL_ONLY: Dict[str, Tuple[str, ...]] = {
    "permission": (), "file": ("poster", "head"), "swarm": ("positions",), "crosstalk": ("thread",),
}

FULL_ONLY_FIELDS: frozenset = frozenset(f for fields in FULL_ONLY.values() for f in fields)

STRIP_WITHOUT_AGENT = frozenset({"appupdate"})

KIND_STYLE: Dict[str, Tuple[str, str]] = {
    "yesno": ("ask", "t"), "choice": ("ask", "t"), "permission": ("ask", "t"), "swarm": ("ask", "t"),
    "died": ("alarm", "t"), "signin": ("alarm", "t"), "finished": ("done", "a"),
    "file": ("soft", "a"), "link": ("soft", "a"), "image": ("soft", "a"), "video": ("soft", "a"), "crosstalk": ("soft", "a"),
    "update": ("none", "p"), "appupdate": ("none", "p"), "notice": ("default", "a"),
}

TYPE_KIND: Dict[str, str] = {
    "session.question": "yesno", "approval.folder_trust": "yesno", "session.plan_approval": "choice",
    "session.permission": "permission", "approval.agent_action": "permission",
    "agent.message": "crosstalk", "session.finished": "finished", "session.died": "died",
    "agent.update_ready": "update", "app.update_available": "appupdate", "swarm.question_climbed": "swarm",
    "provider.needs_login": "signin",
}
TYPE_SHAPES: Dict[str, Tuple[str, ...]] = {
    "session.question": ("yesno", "choice"), "session.plan_approval": ("choice",),
    "agent.message": ("crosstalk", "file", "link", "image", "video"),
}

STRING_KEYS: Tuple[str, ...] = (
    "notify.card.word.yesno", "notify.card.word.choice", "notify.card.word.permission", "notify.card.word.file",
    "notify.card.word.link", "notify.card.word.image", "notify.card.word.video", "notify.card.word.finished",
    "notify.card.word.died", "notify.card.word.update", "notify.card.word.appupdate", "notify.card.word.swarm",
    "notify.card.word.crosstalk", "notify.card.word.signin", "notify.card.word.notice",
    "notify.card.title.ask", "notify.card.title.permission", "notify.card.title.file", "notify.card.title.link",
    "notify.card.title.image", "notify.card.title.video", "notify.card.title.finished", "notify.card.title.died",
    "notify.card.title.update", "notify.card.title.appupdate", "notify.card.title.swarm", "notify.card.title.crosstalk",
    "notify.card.title.signin",
    "notify.card.sub.default", "notify.card.sub.died", "notify.card.sub.appupdate", "notify.card.sub.swarm",
    "notify.card.sub.crosstalk", "notify.card.sub.signin",
    "notify.card.act.yes", "notify.card.act.no", "notify.card.act.reply", "notify.card.act.opt.1", "notify.card.act.opt.2",
    "notify.card.act.opt.3", "notify.card.act.opt.4", "notify.card.act.open_file", "notify.card.act.save_file",
    "notify.card.act.open_link", "notify.card.act.copy_link", "notify.card.act.open", "notify.card.act.save",
    "notify.card.act.play", "notify.card.act.reopen", "notify.card.act.restart_agents", "notify.card.act.later",
    "notify.card.act.install", "notify.card.act.pick.1", "notify.card.act.pick.2", "notify.card.act.answer",
    "notify.card.act.sign_in",
    "notify.card.reply.placeholder", "notify.card.reply.swarm_placeholder",
    "notify.card.row.from", "notify.card.row.asked", "notify.card.row.waiting", "notify.card.row.tool", "notify.card.row.folder",
    "notify.card.row.computer", "notify.card.row.allow", "notify.card.row.first_page", "notify.card.row.page",
    "notify.card.row.address", "notify.card.row.opens_in", "notify.card.row.agent", "notify.card.row.version",
    "notify.card.row.sessions", "notify.card.row.account", "notify.card.row.reason",
    "notify.card.value.waiting_on_answer", "notify.card.value.needs_face_id", "notify.card.value.safari",
    "notify.card.value.from_to", "notify.card.value.you_have", "notify.card.value.done_in", "notify.card.value.exit_code",
    "notify.card.value.file_pages", "notify.card.value.image_size", "notify.card.value.mixed_script",
    "notify.card.reason.refused", "notify.card.reason.expired", "notify.card.reason.missing",
    "notify.card.state.more", "notify.card.state.more_count", "notify.card.state.empty", "notify.card.state.nothing",
    "notify.card.state.no_open", "notify.card.state.answered", "notify.card.state.settled", "notify.card.state.sent",
    "notify.card.state.sent_working", "notify.card.state.not_sent", "notify.card.state.already_answered",
    "notify.card.state.already_used", "notify.card.state.expired", "notify.card.state.open_to_answer",
    "notify.card.state.play_on_computer", "notify.card.state.over_budget", "notify.card.state.closes",
    "notify.card.state.fallback_note",
    "notify.card.answer.sent_reply", "notify.card.answer.allowed", "notify.card.answer.denied", "notify.card.answer.saved_file",
    "notify.card.answer.opening_file", "notify.card.answer.copied", "notify.card.answer.opening_link",
    "notify.card.answer.saved_photos", "notify.card.answer.playing", "notify.card.answer.opening_app",
    "notify.card.answer.opening_agent", "notify.card.answer.reopening", "notify.card.answer.later",
    "notify.card.answer.restarting", "notify.card.answer.installing", "notify.card.answer.swarm_sent",
    "notify.card.answer.sign_in",
    "notify.card.close", "notify.card.lead.permission", "notify.card.unit.files",
    "notify.card.value.file_page", "notify.card.state.answered_auto", "notify.card.where.elsewhere", "notify.card.where.phone",
    "notify.card.state.answered_elsewhere", "notify.card.value.on_side", "notify.card.where.auto", "notify.card.where.computer",
    "notify.inspector.title", "notify.inspector.label", "notify.inspector.col.on", "notify.inspector.col.sound",
    "notify.inspector.col.urgency", "notify.inspector.col.devices", "notify.inspector.play", "notify.inspector.sound.ask",
    "notify.inspector.sound.done", "notify.inspector.sound.alarm", "notify.inspector.sound.soft", "notify.inspector.sound.none",
    "notify.inspector.sound.default", "notify.inspector.level.passive", "notify.inspector.level.active",
    "notify.inspector.level.time_sensitive", "notify.inspector.device.iphone", "notify.inspector.device.computer",
    "notify.inspector.corner", "notify.inspector.shape", "notify.inspector.reset", "notify.inspector.open_card",
    "notify.inspector.no_device", "notify.inspector.view.banner", "notify.inspector.view.card", "notify.inspector.view.lock",
    "notify.inspector.view.center", "notify.inspector.preview",
    "native.notify.generic.title", "native.notify.generic.body", "native.notify.settled", "native.notify.not_sent",
    "native.notify.open_to_answer", "native.notify.play_on_computer",
    "notify.card.q.permission", "notify.card.unit.lines", "notify.card.where.iphone",
)


def kind_for_type(type_id: str) -> str:
    return TYPE_KIND.get(type_id, "notice")


def category_id(kind: str) -> str:
    return f"carnivore.{kind}"


def _clip(text: Any, limit: int) -> str:
    return str(text)[:limit]


def encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def validate_card(kind: str, card: Mapping[str, Any]) -> None:
    if kind not in CARD_FIELDS:
        raise ValueError(f"unknown kind {kind!r}")
    extra = set(card) - set(ALL_CARD_FIELDS) - set(CARD_FIELDS[kind])
    if extra:
        raise ValueError(f"card fields not in kind {kind}: {sorted(extra)}")


def build_payload(
    *, kind: str, type_id: str, title: str, body: str, path: str, thread: str, sub: str = "", lv: Optional[str] = None,
    snd: Optional[str] = None, cap: Optional[str] = None, ttl: Optional[int] = None,
    acts: Optional[List[Tuple[str, str]]] = None, card: Optional[Mapping[str, Any]] = None, more: bool = False,
    media: Optional[Mapping[str, Any]] = None, settle: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    default_snd, default_lv = KIND_STYLE[kind]
    lv = lv or default_lv
    snd = snd or default_snd
    if lv not in LEVELS or snd not in SOUNDS:
        raise ValueError("bad level or sound")
    p: Dict[str, Any] = {
        "title": _clip(title, LIMITS["title"]), "body": _clip(body, LIMITS["body"]), "path": _clip(path, LIMITS["path"]),
        "thread": _clip(thread, LIMITS["thread"]), "v": PAYLOAD_VERSION, "sub": _clip(sub, LIMITS["sub"]),
        "kind": kind, "type": type_id, "lv": lv, "snd": snd,
    }
    if cap:
        if len(cap) != LIMITS["cap"]:
            raise ValueError("a capability is 43 base64url characters")
        p["cap"] = cap
        if ttl is not None:
            p["ttl"] = int(ttl)
    if acts:
        p["acts"] = [[str(i), _clip(label, LIMITS["act_label"])] for i, label in acts[: LIMITS["acts"]]]
    if card is not None:
        validate_card(kind, card)
        p["card"] = dict(card)
    if more:
        p["more"] = True
    if media is not None:
        p["media"] = dict(media)
    if settle is not None:
        if settle.get("where") not in SETTLE_WHERE:
            raise ValueError("bad settle place")
        p["settle"] = dict(settle)
    return trim_payload(p)


def trim_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    p: Dict[str, Any] = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in payload.items()}

    def fits() -> bool:
        return len(encode(p)) <= MAX_PLAINTEXT_BYTES and ("card" not in p or len(encode(p["card"])) <= LIMITS["card_bytes"])

    if fits():
        return p
    card = p.get("card")
    if isinstance(card, dict) and isinstance(card.get("opts"), list):
        card["opts"] = [list(o[:2]) + [""] if len(o) > 2 else list(o) for o in card["opts"]]
        if fits():
            return p
    if "card" in p:
        del p["card"]
        p["more"] = True
        if fits():
            return p
    p["body"] = _clip(p.get("body", ""), LIMITS["body_trimmed"])
    if fits():
        return p
    if "acts" in p:
        p["acts"] = [[i, _clip(label, LIMITS["act_label_trimmed"])] for i, label in p["acts"]]
        if fits():
            return p
    out: Dict[str, Any] = {k: p[k] for k in (*V1_KEYS, "v", "kind", "cap") if k in p}
    out["more"] = True
    for key in ("body", "title", "thread"):
        while len(encode(out)) > MAX_PLAINTEXT_BYTES and out.get(key):
            out[key] = out[key][: len(out[key]) // 2]
    return out
