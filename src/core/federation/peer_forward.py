
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlencode

from src.core.federation import peer_hosts
from src.core.federation.pairing import ANSWER_ALL_MINOR, UPLOAD_MINOR
from src.core.federation.peer_client import PeerClient
from src.core.hosts.identity import REMOTE_ID_PREFIX, parse_remote_session_id

FORWARD, REFUSE, LOCAL, SELF = "forward", "refuse", "local", "self"
NAME, UUID, SID = "name", "uuid", "sid"
SLOW_SECONDS = 45.0
_SLOW = re.compile(r"/(restart|respawn|recreate|wake|sleep|move|fork|upload-file|upload-image)(/|$)|^POST /sessions$")

Ref = Tuple[str, str, str]


@dataclass(frozen=True)
class RawBody:

    data: bytes
    content_type: str


@dataclass(frozen=True)
class Rule:

    method: str
    path: str
    mode: str
    ref: Optional[Ref] = None
    min_minor: int = 0
    why: str = ""


def _f(method: str, path: str, ref: Optional[Ref], min_minor: int = 0) -> Rule:
    return Rule(method, path, FORWARD, ref, min_minor)


def _r(method: str, path: str, why: str) -> Rule:
    return Rule(method, path, REFUSE, None, 0, why)


def _s(method: str, path: str) -> Rule:
    return Rule(method, path, SELF)


def _l(method: str, path: str) -> Rule:
    return Rule(method, path, LOCAL)


_SID, _SNAME = ("path", "session_id", SID), ("path", "session_name", NAME)
_SUUID = ("path", "session_uuid", UUID)
_BINARY = "moves bytes the JSON peer link cannot carry"
_CONVERSATIONS = "the conversation lineage is kept in the owning computer's own datastore"
_SHARE = "needs a share scope no peer grant carries yet"
_OWNER_DISK = "reads or writes the owning computer's own vault and files, and no peer scope covers it yet; do it on that computer"
_TRANSCRIPT = "bookmarks, turns, branch and rewind read and write the owning computer's own transcript and checkpoints"

TABLE: Tuple[Rule, ...] = (
    _f("POST", "/sessions", ("body", "host_key", NAME)),
    _f("GET", "/sessions", ("query", "session_id", SID)),
    _f("DELETE", "/sessions", ("query", "session_id", SID)),
    _f("POST", "/sessions/detach", ("query", "session_id", SID)),
    _f("DELETE", "/sessions/external/{name}", ("path", "name", NAME)),
    _f("POST", "/sessions/respawn", ("body", "session_name", NAME)),
    _f("GET", "/sessions/restart/preview", ("query", "session_name", NAME)),
    _f("POST", "/sessions/{session_uuid}/restart", _SUUID),
    _f("GET", "/sessions/{session_uuid}/restart/accounts", _SUUID),
    _f("POST", "/sessions/recreate", ("body", "session_uuid", UUID)),
    _f("GET", "/sessions/recreate/preview", ("query", "session_uuid", UUID)),
    _f("POST", "/sessions/imported/restart", ("body", "session_uuid", UUID)),
    _f("GET", "/sessions/imported/restart/preview", ("query", "session_uuid", UUID)),
    _f("POST", "/sessions/{session_uuid}/sleep", _SUUID),
    _f("POST", "/sessions/{session_uuid}/wake", _SUUID),
    _f("POST", "/sessions/{session_uuid}/move", _SUUID),
    _r("POST", "/sessions/{session_uuid}/send", "send to is the owner's own action on a session of this computer (#1653); a paired computer's row is sent from that computer"),
    _r("POST", "/sessions/{session_uuid}/send/check", "send to is the owner's own action on a session of this computer (#1653); a paired computer's row is sent from that computer"),
    _f("DELETE", "/sessions/{session_uuid}/asleep", _SUUID),
    _f("DELETE", "/sessions/records/{session_uuid}", _SUUID),
    _f("PATCH", "/sessions/records/{session_uuid}/notifications", _SUUID),
    _f("POST", "/sessions/records/{session_uuid}/unarchive", _SUUID),
    _r("POST", "/sessions/{session_id}/shell", "a paired computer's agent has no companion shell (design 8.6, S8)"),
    _r("GET", "/sessions/{session_id}/shell", "a paired computer's agent has no companion shell (design 8.6, S8)"),
    _r("GET", "/sessions/{session_id}/attach-command", "the argv attaches a terminal to a tmux session on the computer that answers, so a paired computer's session has none here (R1-14)"),
    _f("PATCH", "/sessions/{session_id}/name", _SID),
    _f("PATCH", "/sessions/{session_name}/theme", _SNAME),
    _f("PATCH", "/sessions/{session_name}/pinned-theme", _SNAME),
    _f("PATCH", "/sessions/{session_name}/unread", _SNAME),
    _f("PATCH", "/sessions/{session_name}/background", _SNAME),
    _r("GET", "/sessions/{session_name}/background/image", _BINARY),
    _r("PUT", "/sessions/{session_name}/background/image", _BINARY),
    _r("DELETE", "/sessions/{session_name}/background/image", _BINARY),
    _f("GET", "/sessions/{session_name}/note", _SNAME),
    _f("PUT", "/sessions/{session_name}/note", _SNAME),
    _f("POST", "/sessions/{session_name}/fork", _SNAME),
    _f("PUT", "/sessions/{session_name}/active", _SNAME),
    _f("GET", "/sessions/{session_name}/local-servers", _SNAME),
    _f("POST", "/sessions/{session_id}/interrupt", _SID),
    _f("GET", "/sessions/{session_id}/dialog", _SID),
    _f("POST", "/sessions/{session_id}/dialog/answer", _SID),
    _f("POST", "/sessions/{session_id}/dialog/answer-all", _SID, ANSWER_ALL_MINOR),
    _f("POST", "/sessions/{session_id}/skills/one-shot", _SID),
    _f("GET", "/sessions/{session_id}/skills", _SID),
    _f("GET", "/sessions/{session_id}/skills/scout", _SID),
    _f("POST", "/sessions/{session_id}/skills/scout", _SID),
    _f("GET", "/sessions/{session_id}/skill-fires", _SID),
    _f("POST", "/sessions/upload-file", ("query", "session_id", SID), UPLOAD_MINOR),
    _f("POST", "/sessions/upload-image", ("query", "session_id", SID), UPLOAD_MINOR),
    _r("POST", "/sessions/{session_id}/agent-message", "an agent notifies the owner of the computer it runs on; it is never a peer action"),
    _r("POST", "/sessions/adopt", "adopting attaches a tmux session of the machine that lists it; adopt on that computer"),
    _f("GET", "/sessions/{session_id}/pane-facts", _SID),
    _f("GET", "/sessions/{session_id}/timers", _SID),
    _f("GET", "/sessions/{session_id}/subagents", _SID),
    _f("GET", "/sessions/{session_id}/token-usage", _SID),
    _f("GET", "/sessions/{session_id}/background-work", _SID),
    _f("POST", "/sessions/{session_id}/background-work/{pid}/terminate", _SID),
    _f("POST", "/sessions/{session_id}/background-work/terminate-all", _SID),
    _f("GET", "/sessions/{session_id}/toasts", _SID),
    _f("POST", "/sessions/{session_id}/toasts", _SID),
    _f("POST", "/toasts/{toast_id}/ack", ("query", "session_id", NAME)),
    _s("GET", "/sessions/{session_id}/size-master"),
    _s("PUT", "/sessions/{session_id}/size-master"),
    _s("DELETE", "/sessions/{session_id}/size-master"),
    _r("GET", "/sessions/{session_id}/spectator-links", _SHARE),
    _r("POST", "/sessions/{session_id}/spectator-links", _SHARE),
    _r("DELETE", "/sessions/{session_id}/spectator-links/{link_id}", _SHARE),
    _r("POST", "/sessions/{session_id}/fork-to", _CONVERSATIONS),
    _r("GET", "/sessions/{session_id}/prompt-texts", _CONVERSATIONS),
    *(_r(m, p, _TRANSCRIPT) for m, p in (
        ("GET", "/sessions/{session_uuid}/bookmarks"), ("POST", "/sessions/{session_uuid}/bookmarks"),
        ("GET", "/sessions/{session_uuid}/compactions/{entry_uuid}/preview"),
        ("GET", "/sessions/{session_uuid}/turns"), ("POST", "/sessions/{session_uuid}/branch"),
        ("POST", "/sessions/{session_uuid}/rewind"))),
    _f("POST", "/sessions/{session_id}/mcp/reconnect", _SID),
    _r("POST", "/sessions/records/{session_uuid}/purge", "a hard delete of the owning computer's own files, owner login only, never a peer action"),
    _r("POST", "/sessions/{session_id}/messaging/send", "a bound agent texts the owner of the computer it runs on; it is never a peer action"),
    _r("GET", "/sessions/{session_uuid}/conversations", _CONVERSATIONS),
    _r("POST", "/sessions/{session_uuid}/conversations/{conversation_id}/resume", _CONVERSATIONS),
    _r("GET", "/sessions/{session_uuid}/timeline", "the timeline joins the owning computer's conversations, marks and stats, kept in its own datastore"),
    _r("GET", "/sessions/{session_uuid}/timeline/peek", "the peek reads the owning computer's own transcript"),
    _r("POST", "/sessions/{session_uuid}/move-folder", "moves the owning computer's working folder on its own disk; the owner stays the only owner, so move it on that computer"),
    _r("GET", "/cplugs/save/sessions/{session_uuid}/points", _OWNER_DISK),
    _r("POST", "/cplugs/save/sessions/{session_uuid}/points/{point_id}/pin", _OWNER_DISK),
    _r("DELETE", "/cplugs/save/sessions/{session_uuid}/points/{point_id}", _OWNER_DISK),
    _r("POST", "/cplugs/save/sessions/{session_uuid}/points/{point_id}/restore", "a restore writes files back onto the owning computer's own disk; restore on that computer"),
    *(_l(m, p) for m, p in (
        ("GET", "/cplugs/huddle/lists/{key}/sessions"),
        ("GET", "/sessions/list"), ("GET", "/sessions/recent"), ("GET", "/sessions/records"),
        ("GET", "/sessions/asleep"), ("GET", "/sessions/list-and-asleep"), ("GET", "/sessions/companions"), ("GET", "/sessions/attachable"), ("GET", "/sessions/attention"),
        ("GET", "/sessions/background"), ("GET", "/sessions/import-status"), ("GET", "/sessions/logs"),
        ("GET", "/sessions/scrollback-search"), ("POST", "/sessions/command"),
        ("GET", "/sessions/restore-offer"), ("POST", "/sessions/restore-offer/accept"),
        ("POST", "/sessions/restore-offer/decline"), ("GET", "/session-backgrounds"),
        ("GET", "/session-groups"), ("POST", "/session-groups"), ("DELETE", "/session-groups/{group_uuid}"),
        ("PATCH", "/session-groups/{group_uuid}"), ("PUT", "/session-groups/{group_uuid}/icon"),
        ("POST", "/session-groups/{group_uuid}/order"), ("PUT", "/session-groups/{group_uuid}/style"),
        ("POST", "/session-groups/assign"), ("POST", "/session-groups/order"),
        ("POST", "/layouts/{layout_uuid}/members"), ("DELETE", "/layouts/{layout_uuid}/members/{session_uuid}"),
        ("PUT", "/layouts/{layout_uuid}/members/{session_uuid}/broadcast"),
        ("POST", "/library/projects/{source_id}/merge"), ("DELETE", "/library/sessions/{session_uuid}"),
        ("GET", "/sessions/listing"),
        ("GET", "/sessions/{session_id}/git-status"), ("GET", "/sessions/{session_id}/git-diff"),
        ("GET", "/sessions/{session_id}/tasks"),
        ("GET", "/sessions/{session_id}/upload-image"),
        ("DELETE", "/swarm/members/{session_uuid}"),
        ("GET", "/sessions/latest-lines"), ("GET", "/sessions/usage"), ("GET", "/sessions/{session_uuid}/contents"),
        ("PATCH", "/sessions/records/{session_uuid}/description"), ("GET", "/sessions/roster"),
        ("GET", "/cplugs/huddle/sessions/{session_uuid}/prefs"), ("PUT", "/cplugs/huddle/sessions/{session_uuid}/prefs"),
        ("PUT", "/cplugs/huddle/sessions/{session_uuid}/dnd"),
        ("GET", "/catalog/account/sessions"), ("DELETE", "/catalog/account/sessions/{sid}"),
        ("POST", "/catalog/account/sessions/revoke-others"),
        ("POST", "/native-devices"), ("GET", "/native-devices"), ("DELETE", "/native-devices/{row_id}"))),
)

RULES: Dict[Tuple[str, str], Rule] = {(r.method, r.path): r for r in TABLE}
_SESSION_PATH = re.compile(r"/(sessions|session-groups|session-backgrounds)(/|$)|/layouts/.*members")
_PATTERNS: List[Tuple[re.Pattern, Rule]] = sorted(
    ((re.compile("^/api/v1" + re.sub(r"\{[^}]+\}", "([^/]+)", r.path) + "$"), r) for r in TABLE),
    key=lambda pr: pr[1].path.count("{"))
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def is_session_path(path: str) -> bool:
    return bool(_SESSION_PATH.search(path)) or bool(re.search(r"\{[a-z_]*session[a-z_]*\}", path))


def rule_for(method: str, url_path: str) -> Optional[Rule]:
    for pattern, rule in _PATTERNS:
        if rule.method == method and pattern.match(url_path):
            return rule
    return None


@dataclass(frozen=True)
class Target:

    peer: peer_hosts.PeerRow
    name: str
    uuid: Optional[str]


def could_name_a_peer_session(value: Optional[str]) -> bool:
    return bool(value) and (value.startswith("remote:") or bool(_UUID_RE.match(value)))  # type: ignore[union-attr]


def _peer_by_key(conn: sqlite3.Connection, key: str) -> Optional[peer_hosts.PeerRow]:
    row = conn.execute("SELECT peer_install_id FROM hosts WHERE key = ? AND kind = 'peer'", (key,)).fetchone()
    return peer_hosts.get(conn, row[0]) if row else None


def resolve(conn: sqlite3.Connection, value: Optional[str]) -> Optional[Target]:
    if not value:
        return None
    parsed = parse_remote_session_id(value)
    if parsed is not None:
        peer = _peer_by_key(conn, parsed[0])
        if peer is None:
            return None
        row = conn.execute("SELECT peer_session_uuid FROM peer_sessions WHERE host_key = ? AND peer_name = ?",
                           (peer.key, parsed[1])).fetchone()
        return Target(peer, parsed[1], row[0] if row else None)
    if not _UUID_RE.match(value):
        return None
    row = conn.execute("SELECT ps.host_key, ps.peer_session_uuid, ps.peer_name FROM peer_sessions ps "
                       "JOIN sessions s ON s.id = ps.session_id WHERE s.session_uuid = ?", (value,)).fetchone()
    peer = _peer_by_key(conn, row[0]) if row else None
    return Target(peer, row[2], row[1]) if peer is not None and row else None


def create_peer(conn: sqlite3.Connection, host_key: Optional[str]) -> Optional[peer_hosts.PeerRow]:
    if not host_key or host_key == "local":
        return None
    peer = _peer_by_key(conn, host_key)
    if peer is not None:
        return peer
    row = conn.execute("SELECT ssh_target FROM hosts WHERE key = ? AND kind != 'peer'", (host_key,)).fetchone()
    if not row or not row[0]:
        return None
    return next((p for p in peer_hosts.list_peers(conn) if p.ssh_target == row[0] and p.peer_state == "connected"), None)


def build_request(rule: Rule, target_value: str, path_params: Mapping[str, str], query: List[Tuple[str, str]],
                  body: Any) -> Tuple[str, Any]:
    where, name, _ = rule.ref if rule.ref else ("", "", "")
    fill = {k: quote(target_value if where == "path" and k == name else v, safe="") for k, v in path_params.items()}
    path = re.sub(r"\{([^}]+)\}", lambda m: fill[m.group(1)], rule.path)
    pairs = [(k, target_value if where == "query" and k == name else v) for k, v in query]
    if where == "body" and isinstance(body, dict):
        body = {**body, name: target_value}
    return path + (("?" + urlencode(pairs)) if pairs else ""), body


async def send(client: PeerClient, rule: Rule, path: str, body: Any):
    slow = bool(_SLOW.search(f"{rule.method} {rule.path}"))
    if isinstance(body, RawBody):
        return await client.request(rule.method, path, content=body.data, headers={"Content-Type": body.content_type},
                                    timeout=SLOW_SECONDS if slow else None)
    return await client.request(rule.method, path, json=body, timeout=SLOW_SECONDS if slow else None)


def wire_session_reply(raw: bytes, peer_key: str, peer_label: str, name: str) -> Optional[bytes]:
    try:
        answer = json.loads(raw)
    except ValueError:
        return None
    session = answer.get("session") if isinstance(answer, dict) else None
    if not isinstance(session, dict) or not isinstance(session.get("id"), str):
        return None
    session["id"] = f"{REMOTE_ID_PREFIX}{peer_key}:{name}"
    if "host_key" in answer:
        answer["host_key"], answer["host_label"] = peer_key, peer_label
    return json.dumps(answer).encode()
