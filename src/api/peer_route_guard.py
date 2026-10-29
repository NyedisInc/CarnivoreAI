
from __future__ import annotations

import json
import secrets
from typing import Any, List, Optional, Tuple

import structlog
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from starlette.requests import HTTPConnection

from src.api import peer_auth
from src.config import settings
from src.core.federation import peer_forward, peer_links, peer_listing, peer_token
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.federation.peer_forward import FORWARD, LOCAL, SELF, SID, UUID
from src.core.launch_profiles import create_seam
from src.core.hosts.identity import REMOTE_ID_PREFIX, remote_session_id

logger = structlog.get_logger()
MAX_SCAN_BODY = 256 * 1024
UPLOAD_PATHS = ("/sessions/upload-file", "/sessions/upload-image")
FAR_LAUNCHER_FLAG = "agent_type_is_far"


class PeerForwarded(Exception):

    def __init__(self, response: Response) -> None:
        super().__init__("forwarded")
        self.response = response


def _refusal(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _bearer(conn: HTTPConnection) -> Optional[str]:
    value = conn.headers.get("authorization", "")
    return value[7:] if value[:7].lower() == "bearer " else None


async def _body(conn: HTTPConnection) -> Any:
    if conn.scope["method"] not in ("POST", "PUT", "PATCH", "DELETE") or "json" not in conn.headers.get("content-type", ""):
        return None
    raw = await conn.body()  # type: ignore[attr-defined]
    if not raw or len(raw) > MAX_SCAN_BODY:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _values(conn: HTTPConnection, body: Any) -> List[str]:
    found = [str(v) for v in conn.path_params.values()] + [v for _, v in conn.query_params.multi_items()]
    if isinstance(body, dict):
        found += [v for v in body.values() if isinstance(v, str)]
    return found


async def _raw_upload(conn: HTTPConnection) -> peer_forward.RawBody:
    cfg = settings.load_auth_config().uploads
    limit = (max(cfg.max_size_mb, cfg.max_file_size_mb) + 1) * 1024 * 1024
    too_large = _refusal(413, "upload_too_large", "that file is larger than an upload may be")
    declared = conn.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    form = await conn.form()  # type: ignore[attr-defined]
    part = form.get("file")
    if part is None or not hasattr(part, "read"):
        raise _refusal(400, "upload_missing_file", "no file was sent")
    data = await part.read(limit + 1)
    if len(data) > limit:
        raise too_large
    name = "".join(c for c in (getattr(part, "filename", "") or "") if c not in '"\r\n\\')
    boundary = "cloude-" + secrets.token_hex(16)
    head = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
    head += "Content-Type: application/octet-stream\r\n\r\n"
    return peer_forward.RawBody(head.encode() + data + f"\r\n--{boundary}--\r\n".encode(),
                                f"multipart/form-data; boundary={boundary}")


def _lookup(value: Optional[str]) -> Optional[peer_forward.Target]:
    if not peer_forward.could_name_a_peer_session(value):
        return None
    with _open() as conn:
        return peer_forward.resolve(conn, value)


def create_target(host_key: Optional[str]) -> Optional[Any]:
    if not host_key or host_key == "local":
        return None
    with _open() as conn:
        return peer_forward.create_peer(conn, host_key)


def _open():
    from contextlib import closing

    return closing(peer_auth.open_db())


async def _authenticate(conn: HTTPConnection, token: Optional[str]) -> bool:
    if token and peer_token.is_peer_token(token):
        if conn.scope.get("via_link"):
            raise HTTPException(status_code=403, detail="peer tokens are not accepted over the link")
        await peer_auth._authorize_peer(token, "sessions")
        return True
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token) if token else None
    await peer_auth.owner_check(conn, creds)  # type: ignore[arg-type]
    return False


def _extract(rule: peer_forward.Rule, conn: HTTPConnection, body: Any) -> Optional[str]:
    where, name, _ = rule.ref  # type: ignore[misc]
    if where == "path":
        return conn.path_params.get(name)
    if where == "query":
        return conn.query_params.get(name)
    return body.get(name) if isinstance(body, dict) and isinstance(body.get(name), str) else None


async def forward_reply(rule: peer_forward.Rule, peer: Any, path: str, body: Any, retry: Optional[Tuple[str, Any]] = None,
                 name: Optional[str] = None) -> Response:
    links = peer_links.LINKS
    client = links.client(peer.peer_install_id) if links is not None else None
    if client is None:
        raise _refusal(503, "peer_unavailable", f"{peer.label} is not connected")
    if rule.min_minor > links.minor(peer.peer_install_id):  # type: ignore[union-attr]
        raise _refusal(409, "peer_capability_missing", f"{peer.label} runs an older Carnivore without this action")
    try:
        answer = await peer_forward.send(client, rule, path, body)
        if answer.status_code == 404 and retry is not None:
            answer = await peer_forward.send(client, rule, *retry)
    except PeerRefused as exc:
        raise _refusal(502, "peer_unavailable", f"{peer.label} refused the link ({exc.code})") from None
    except PeerUnreachable as exc:
        raise _refusal(504 if str(exc) == "timeout" else 502, "peer_unavailable", f"{peer.label} did not answer") from None
    content = answer.body
    if rule.method == "POST" and rule.path == "/sessions" and answer.status_code == 201:
        content = await _name_created(client, peer, answer.body) or content
    elif name is not None and answer.status_code in (200, 201):
        content = peer_forward.wire_session_reply(answer.body, peer.key, peer.label, name) or content
    return Response(content=content, status_code=answer.status_code,
                    media_type=answer.headers.get("content-type", "application/json"))


async def _name_created(client: Any, peer: Any, raw: bytes) -> Optional[bytes]:
    try:
        created = json.loads(raw)
        info = (await client.request("GET", f"/sessions?session_id={created['id']}")).json()
        created["id"] = remote_session_id(peer.key, str(info["tmux_session"]))
        return json.dumps(created).encode()
    except (PeerUnreachable, PeerRefused, ValueError, KeyError, TypeError):
        logger.info("peer_create_reply_unnamed", peer=peer.key)
        return None


async def peer_route_guard(conn: HTTPConnection) -> None:
    path, method = conn.url.path, conn.scope.get("method", "")
    if conn.scope["type"] != "http" or method in ("OPTIONS", "HEAD") or not path.startswith("/api/v1/"):
        return
    rule = peer_forward.rule_for(method, path)
    if rule is None and not peer_forward.is_session_path(path):
        return
    token = _bearer(conn)
    body = await _body(conn)
    if rule is not None and rule.mode in (LOCAL, SELF):
        return
    if rule is None or rule.mode != FORWARD:
        values = [v for v in _values(conn, body) if peer_forward.could_name_a_peer_session(v)]
        named = False
        for value in values:
            named = named or await run_in_threadpool(_lookup, value) is not None
        if not named:
            return
        await _authenticate(conn, token)
        why = rule.why if rule is not None else "this action has no forward to the owner yet"
        raise _refusal(409, "peer_route_unsupported", f"{method} {path} is not available for a session on a paired computer: {why}")
    value = _extract(rule, conn, body)
    if not value:
        return
    creating = rule.path == "/sessions" and method == "POST"
    if token and peer_token.is_peer_token(token):
        target = await run_in_threadpool(create_target if creating else _lookup, value)
        if target is not None or value.startswith(REMOTE_ID_PREFIX):
            await _authenticate(conn, token)
            raise _refusal(409, "not_local", "a paired computer may act only on the sessions this computer owns")
        return
    target = await run_in_threadpool(create_target if creating else _lookup, value)
    if target is None:
        return
    await _authenticate(conn, token)
    peer = target if creating else target.peer
    if creating:
        if isinstance(body, dict) and (body.get("account_id") or body.get("account_pinned")):
            raise _refusal(400, "account_not_local", "an account is chosen on the computer that runs the session")
        sent, forward_value = body, "local"
        if isinstance(body, dict):
            sent = {k: v for k, v in body.items() if k != FAR_LAUNCHER_FLAG}
            if body.get("agent_type") and body.get(FAR_LAUNCHER_FLAG) is not True:
                sent["agent_type"] = create_seam.far_host_agent_type(settings, body["agent_type"])
    else:
        form = rule.ref[2]  # type: ignore[index]
        forward_value = target.uuid if form == UUID else (
            peer_listing.owner_session_id(target.peer.key, target.name) or target.name) if form == SID else target.name
        if forward_value is None:
            raise _refusal(404, "peer_session_unknown", "the paired computer has not listed this session yet")
        sent = body
        if rule.path in UPLOAD_PATHS:
            sent = await _raw_upload(conn)
    args = (dict(conn.path_params), list(conn.query_params.multi_items()), sent)
    by_name = None if creating or forward_value == target.name or rule.ref[2] != SID else (  # type: ignore[index]
        peer_forward.build_request(rule, target.name, *args))
    raise PeerForwarded(await forward_reply(rule, peer, *peer_forward.build_request(rule, forward_value, *args), retry=by_name,
                                  name=None if creating else target.name))
