
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any, Dict, List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.messaging import message_store, notices, store
from src.core.messaging.client import BAD_ANSWER, REJECTED, ProviderError
from src.core.messaging.events import BRIDGE_KEY, DETAIL_KEY, SKIPPED_KEY
from src.core.messaging.secrets import OpReadError, ProviderSecrets, match_of, new_match_key, read_op_reference

logger = structlog.get_logger()
router = APIRouter(prefix="/messaging", tags=["messaging"], dependencies=[Depends(require_auth)])

TEST_INTERVAL_SECONDS = 10.0
_last_test: Dict[str, float] = {}

Direction = Literal["in", "out", "both"]


class _Strict(BaseModel):
    """Unknown fields are a 422, never ignored."""

    model_config = ConfigDict(extra="forbid")


class ProviderCreate(_Strict):

    name: str = Field(..., min_length=1, max_length=40)
    base_url: str = Field(..., min_length=8, max_length=500)
    token: Optional[str] = Field(None, max_length=1000)
    token_ref: Optional[str] = Field(None, max_length=300)
    owner_senders: List[str] = Field(..., min_length=1, max_length=20)
    owner_label: str = Field("the owner", min_length=1, max_length=40)
    allow_private: bool = False
    allow_plain_http: bool = False


class ProviderPatch(_Strict):

    name: Optional[str] = Field(None, min_length=1, max_length=40)
    base_url: Optional[str] = Field(None, max_length=500)
    token: Optional[str] = Field(None, max_length=1000)
    token_ref: Optional[str] = Field(None, max_length=300)
    owner_senders: Optional[List[str]] = Field(None, max_length=20)
    owner_label: Optional[str] = Field(None, min_length=1, max_length=40)
    allow_private: Optional[bool] = None
    allow_plain_http: Optional[bool] = None
    enabled: Optional[bool] = None


class TestBody(_Strict):

    conversation_id: str


class ConversationCreate(_Strict):
    """POST /conversations: the provider's conversation id (write-only) and a label."""

    provider_id: str
    conversation: str = Field(..., min_length=1, max_length=400)
    label: str = Field(..., min_length=1, max_length=80)


class ConversationPatch(_Strict):

    label: str = Field(..., min_length=1, max_length=80)


class BindingCreate(_Strict):

    conversation_id: str
    session_uuid: str = Field(..., min_length=8, max_length=64)
    direction: Direction
    default: bool = False


class BindingPatch(_Strict):

    direction: Optional[Direction] = None
    default: Optional[bool] = None
    held_notice: Optional[bool] = None


def runtime_of(request: Any) -> Any:
    rt = getattr(request.app.state, "messaging", None)
    if rt is None:
        raise HTTPException(status_code=503, detail={"code": "messaging_unavailable"})
    return rt


def _refuse(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


FLOW_FLOWING, FLOW_STALE = "flowing", "stale"


def flow_of(stream_state: Optional[str], bridge: Optional[Dict[str, Any]]) -> str:
    return FLOW_FLOWING if stream_state == "live" and bridge else FLOW_STALE


def provider_view(row: Dict[str, Any], state: Any, traffic: Optional[Dict[str, Optional[float]]] = None) -> Dict[str, Any]:
    secrets = state.secrets if state is not None else None
    bridge = state.extra.get(BRIDGE_KEY) if state is not None else None
    traffic = traffic or {}
    return {
        "id": row["id"], "name": row["name"], "owner_label": row["owner_label"], "enabled": row["enabled"],
        "allow_private": row["allow_private"], "allow_plain_http": row["allow_plain_http"],
        "capabilities": row["capabilities"],
        "idempotency": {"proven": row.get("replay_proven_at") is not None, "last_proven_at": row.get("replay_proven_at")},
        "stream": {"state": row["stream_state"], "cursor": row["cursor"], "gap": row["gap"],
                   "last_event_at": row["last_event_at"],
                   "last_inbound_at": traffic.get("last_inbound_at"), "last_outbound_at": traffic.get("last_outbound_at"),
                   "bridge": bridge, "flow": flow_of(row["stream_state"], bridge),
                   "detail": state.extra.get(DETAIL_KEY) if state is not None else None,
                   "skipped_events": int(state.extra.get(SKIPPED_KEY, 0)) if state is not None else 0},
        "secrets": {"base_url": {"set": bool(secrets and secrets.base_url)},
                    "token": {"set": bool(secrets and secrets.token)},
                    "owner_senders": {"set": bool(secrets and secrets.owner_senders),
                                      "count": len(secrets.owner_senders) if secrets else 0}},
    }


async def _view(row: Dict[str, Any], state: Any) -> Dict[str, Any]:
    return provider_view(row, state, await asyncio.to_thread(message_store.last_traffic, row["id"]))


async def _token(token: Optional[str], token_ref: Optional[str], *, required: bool) -> Optional[str]:
    if token and token_ref:
        raise _refuse(422, "token_and_token_ref")
    if token_ref:
        try:
            return await read_op_reference(token_ref)
        except OpReadError:
            raise _refuse(422, "token_ref_unreadable") from None
    if required and not token:
        raise _refuse(422, "token_required")
    return token or None


def _provider_down(exc: ProviderError) -> HTTPException:
    if exc.code == BAD_ANSWER:
        return _refuse(422, "cpp_unsupported")
    body: Dict[str, Any] = {"code": REJECTED if exc.code == REJECTED else "provider_unreachable"}
    if exc.detail:
        body.update(status=exc.status, reason=exc.detail)
    return HTTPException(status_code=502, detail=body)


async def _probe(rt: Any, row: Dict[str, Any], secrets: ProviderSecrets) -> Dict[str, Any]:
    try:
        caps = await rt.client_factory(row, secrets).capabilities()
    except ProviderError as exc:
        if exc.code == REJECTED:
            raise HTTPException(status_code=502, detail={"code": REJECTED, "status": exc.status,
                                                         "reason": exc.detail}) from None
        raise _provider_down(exc) from None
    return caps.as_json()


def _state(rt: Any, provider_id: str) -> Any:
    state = rt.providers.get(provider_id)
    if state is None:
        if store.get_provider(provider_id) is None:
            raise _refuse(404, "provider_not_found")
        raise _refuse(409, "provider_not_loaded")
    return state


@router.get("/providers")
async def list_providers(request: Request) -> Dict[str, Any]:
    """Every provider with its stream state; never a secret. Output: {providers: [...]}."""
    rt = runtime_of(request)
    rows = await asyncio.to_thread(store.list_providers)
    return {"providers": [await _view(r, rt.providers.get(r["id"])) for r in rows]}


@router.post("/providers", status_code=201)
async def create_provider(request: Request, body: ProviderCreate) -> Dict[str, Any]:
    """Add a provider: probe its capabilities, store its secrets in the Keychain (verified), then the row.

    Raises: 422 cpp_unsupported / token_*; 502 provider_unreachable; 503 keychain_unavailable.
    """
    rt = runtime_of(request)
    token = await _token(body.token, body.token_ref, required=True)
    provider_id = store.new_id("p_")
    secrets = ProviderSecrets(base_url=body.base_url.strip(), token=str(token),
                              owner_senders=tuple(s.strip() for s in body.owner_senders if s.strip()),
                              match_key=new_match_key())
    draft = {"id": provider_id, "allow_private": body.allow_private, "allow_plain_http": body.allow_plain_http}
    caps = await _probe(rt, draft, secrets)
    if not await rt.secrets.save(provider_id, secrets):
        raise _refuse(503, "keychain_unavailable")
    row = await asyncio.to_thread(store.create_provider, provider_id=provider_id, name=body.name.strip(),
                                  owner_label=body.owner_label.strip(), allow_private=body.allow_private,
                                  allow_plain_http=body.allow_plain_http, capabilities=caps)
    state = await rt.load(provider_id)
    logger.info("messaging_provider_created", provider_id=provider_id)
    return await _view(row, state)


@router.patch("/providers/{provider_id}")
async def update_provider(request: Request, provider_id: str, body: ProviderPatch) -> Dict[str, Any]:
    """Change a provider; a new URL or token is probed before it is stored. Raises 404, 422, 502, 503."""
    rt = runtime_of(request)
    state = _state(rt, provider_id)
    token = await _token(body.token, body.token_ref, required=False)
    secrets = state.secrets
    changed = False
    fields = body.model_dump(exclude_none=True, include={"name", "owner_label", "enabled", "allow_private",
                                                         "allow_plain_http"})
    if body.base_url and body.base_url.strip():
        secrets, changed = replace(secrets, base_url=body.base_url.strip()), True
        fields.setdefault("allow_private", False)
        fields.setdefault("allow_plain_http", False)
    if token:
        secrets, changed = replace(secrets, token=token), True
    senders = tuple(s.strip() for s in (body.owner_senders or []) if s.strip())
    if senders:
        secrets, changed = replace(secrets, owner_senders=senders), True
    if changed or "allow_private" in fields or "allow_plain_http" in fields:
        draft = {**state.row, **fields}
        caps = await _probe(rt, draft, secrets)
        fields["capabilities"] = caps
    if changed and not await rt.secrets.save(provider_id, secrets):
        raise _refuse(503, "keychain_unavailable")
    row = await asyncio.to_thread(store.update_provider, provider_id, **fields)
    return await _view(row, await rt.load(provider_id))


@router.delete("/providers/{provider_id}")
async def delete_provider(request: Request, provider_id: str) -> Dict[str, Any]:
    """Remove a provider, its conversations, bindings and Keychain item; held rows fail. Raises 404."""
    rt = runtime_of(request)
    await rt.unload(provider_id)
    if not await asyncio.to_thread(store.delete_provider, provider_id):
        raise _refuse(404, "provider_not_found")
    await rt.secrets.delete(provider_id)
    return {"deleted": True}


@router.post("/providers/{provider_id}/test")
async def test_provider(request: Request, provider_id: str, body: TestBody) -> Dict[str, Any]:
    """One fixed-copy test text into a conversation of this provider, at most once per 10 s. Raises 404, 429."""
    rt = runtime_of(request)
    state = _state(rt, provider_id)
    conv = await asyncio.to_thread(store.get_conversation, body.conversation_id)
    if conv is None or conv["provider_id"] != provider_id:
        raise _refuse(404, "conversation_not_found")
    now = time.monotonic()
    if now - _last_test.get(provider_id, -TEST_INTERVAL_SECONDS) < TEST_INTERVAL_SECONDS:
        raise HTTPException(status_code=429, detail={"code": "rate_limited"}, headers={"Retry-After": "10"})
    _last_test[provider_id] = now
    sent = await rt.send_notice(state, conv["id"], notices.TEST, None)
    return {"sent": sent}


@router.get("/providers/{provider_id}/conversations")
async def provider_conversations(request: Request, provider_id: str) -> Dict[str, Any]:
    """The provider's own conversation list for the setup picker (labels, routable flags). Raises 404, 502."""
    rt = runtime_of(request)
    state = _state(rt, provider_id)
    try:
        entries = await state.client.conversations()
    except ProviderError as exc:
        raise _provider_down(exc) from None
    return {"conversations": [{"conversation": e.conversation, "label": e.label, "routable": e.routable,
                               "participants": len(e.participants)} for e in entries]}


async def _require_routable(state: Any, conversation: str) -> None:
    try:
        entries = await state.client.conversations()
    except ProviderError as exc:
        raise _provider_down(exc) from None
    if not any(e.conversation == conversation and e.routable for e in entries):
        logger.info("messaging_bind_refused", provider_id=state.id, reason="not_routable")
        raise _refuse(422, "not_routable")


@router.get("/conversations")
async def list_conversations(request: Request, provider_id: Optional[str] = None) -> Dict[str, Any]:
    """Conversation rows (label and provider only). Output: {conversations: [...]}."""
    runtime_of(request)
    return {"conversations": await asyncio.to_thread(store.list_conversations, provider_id)}


@router.post("/conversations", status_code=201)
async def create_conversation(request: Request, body: ConversationCreate) -> Dict[str, Any]:
    """Add a provider conversation; refused unless the provider lists it as routable. Raises 404, 409, 422, 502, 503."""
    rt = runtime_of(request)
    state = _state(rt, body.provider_id)
    await _require_routable(state, body.conversation)
    conversation_id = store.new_id("c_")
    try:
        row = await asyncio.to_thread(store.create_conversation, conversation_id=conversation_id,
                                      provider_id=state.id, label=body.label.strip(),
                                      match_key=match_of(state.secrets.match_key, body.conversation))
    except store.StoreRefused as exc:
        raise _refuse(409, exc.code) from None
    if not await rt.secrets.save(state.id, state.secrets.with_conversation(conversation_id, body.conversation)):
        await asyncio.to_thread(store.delete_conversation, conversation_id)
        raise _refuse(503, "keychain_unavailable")
    await rt.load(state.id)
    return {k: v for k, v in row.items() if k != "match_key"}


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(request: Request, conversation_id: str, body: ConversationPatch) -> Dict[str, Any]:
    """Relabel a conversation. Raises 404."""
    runtime_of(request)
    row = await asyncio.to_thread(store.rename_conversation, conversation_id, body.label.strip())
    if row is None:
        raise _refuse(404, "conversation_not_found")
    return {k: v for k, v in row.items() if k != "match_key"}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str) -> Dict[str, Any]:
    """Remove a conversation, its bindings and its Keychain field; held rows fail ``unbound``. Raises 404."""
    rt = runtime_of(request)
    conv = await asyncio.to_thread(store.get_conversation, conversation_id)
    if conv is None:
        raise _refuse(404, "conversation_not_found")
    await asyncio.to_thread(store.delete_conversation, conversation_id)
    state = rt.providers.get(conv["provider_id"])
    if state is not None:
        await rt.secrets.save(state.id, state.secrets.without_conversation(conversation_id))
        await rt.load(state.id)
    return {"deleted": True}


def _check_direction(state: Any, direction: str) -> None:
    caps = state.caps
    inbound_ok = bool(caps.get("receive")) and caps.get("max_identity") == "strong"
    if (direction in store.INBOUND and not inbound_ok) or (direction in store.OUTBOUND and not caps.get("send")):
        raise _refuse(422, "direction_unsupported")


async def _binding_rows(request: Request, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from src.core.messaging.delivery import session_cards

    cards = await session_cards(request.app) if rows else {}
    return [{**r, "session_name": (cards.get(r["session_uuid"]) or {}).get("name")} for r in rows]


@router.get("/bindings")
async def list_bindings(request: Request, session_uuid: Optional[str] = None) -> Dict[str, Any]:
    """Bindings (optionally one session's), with held counts and session names. Output: {bindings: [...]}."""
    runtime_of(request)
    rows = await asyncio.to_thread(store.list_bindings, session_uuid=session_uuid)
    return {"bindings": await _binding_rows(request, rows)}


@router.post("/bindings", status_code=201)
async def create_binding(request: Request, body: BindingCreate) -> Dict[str, Any]:
    """Bind a session to a conversation, re-checking the provider still lists it as routable.

    Raises: 404 conversation_not_found / session_not_found; 409 already_bound; 422 direction_unsupported /
      not_routable; 502 provider_unreachable.
    """
    rt = runtime_of(request)
    conv = await asyncio.to_thread(store.get_conversation, body.conversation_id)
    if conv is None:
        raise _refuse(404, "conversation_not_found")
    state = _state(rt, conv["provider_id"])
    _check_direction(state, body.direction)
    from src.core.messaging.delivery import _row_exists

    if await asyncio.to_thread(_row_exists, body.session_uuid) is not True:
        raise _refuse(404, "session_not_found")
    await _require_routable(state, state.secrets.conversations.get(conv["id"], ""))
    try:
        row = await asyncio.to_thread(store.create_binding, conversation_id=conv["id"], session_uuid=body.session_uuid,
                                      direction=body.direction, is_default=body.default, created_by="owner")
    except store.StoreRefused as exc:
        raise _refuse(404 if exc.code == "conversation_not_found" else 409, exc.code) from None
    rt.wake(body.session_uuid)
    logger.info("messaging_bound", binding_id=row["id"], direction=body.direction)
    return (await _binding_rows(request, [{**row, "held": 0}]))[0]


@router.patch("/bindings/{binding_id}")
async def update_binding(request: Request, binding_id: str, body: BindingPatch) -> Dict[str, Any]:
    """Change a binding's direction, default or held notice. Raises 404, 422."""
    rt = runtime_of(request)
    current = await asyncio.to_thread(store.get_binding, binding_id)
    if current is None:
        raise _refuse(404, "binding_not_found")
    if body.direction is not None:
        conv = await asyncio.to_thread(store.get_conversation, current["conversation_id"])
        _check_direction(_state(rt, conv["provider_id"]), body.direction)
    row = await asyncio.to_thread(store.update_binding, binding_id, direction=body.direction,
                                  is_default=body.default, held_notice=body.held_notice)
    rt.wake(row["session_uuid"])
    return (await _binding_rows(request, [{**row, "held": current.get("held", 0)}]))[0]


@router.delete("/bindings/{binding_id}")
async def delete_binding(request: Request, binding_id: str) -> Dict[str, Any]:
    """Unbind; the binding's held rows fail ``unbound``. Raises 404."""
    runtime_of(request)
    if not await asyncio.to_thread(store.delete_binding, binding_id):
        raise _refuse(404, "binding_not_found")
    return {"deleted": True}


@router.get("/messages")
async def list_messages(request: Request, binding: Optional[str] = None, status: Optional[str] = None,
                        before: Optional[float] = None, limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    runtime_of(request)
    rows = await asyncio.to_thread(message_store.list_messages, binding_id=binding, status=status, before=before,
                                   limit=limit)
    return {"messages": rows}


@router.post("/messages/{message_id}/retry")
async def retry_message(request: Request, message_id: str) -> Dict[str, Any]:
    """Queue a failed inbound row again. Raises 409 not_retriable."""
    rt = runtime_of(request)
    row = await asyncio.to_thread(message_store.retry, message_id)
    if row is None:
        raise _refuse(409, "not_retriable")
    if row.get("session_uuid"):
        rt.wake(row["session_uuid"])
    return row
