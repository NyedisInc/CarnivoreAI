
from __future__ import annotations

from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api import account_gates
from src.api.auth import require_auth
from src.api.spectator_listing import iso_utc
from src.core.relay_e2ee import share_fragment
from src.core.relay_lifecycle import NOT_RUNNING, RelayUnavailable
from src.core.relay_identity.session import RelayAuthError
from src.core.spectator.revoke import notify_revoked, revoke_all_live
from src.core.spectator_links_store import (
    DEFAULT_TTL_SECONDS,
    MAX_LABEL_LENGTH,
    MAX_TTL_SECONDS,
    MIN_TTL_SECONDS,
    LinkKeysUnavailableError,
    SpectatorLink,
)

logger = structlog.get_logger()

router = APIRouter()


class SpectatorLinkRequest(BaseModel):

    ttl_seconds: Optional[int] = Field(default=None)
    label: Optional[str] = Field(default=None, max_length=MAX_LABEL_LENGTH)


class SpectatorLinkView(BaseModel):

    id: str
    session_id: str
    label: Optional[str]
    created_at: str
    expires_at: str
    url: Optional[str] = None


class SpectatorLinkMinted(BaseModel):
    """The mint response.
    """

    id: str
    url: str
    expires_at: str


class SpectatorLinkList(BaseModel):
    """Every live share on one session, and whether a new one can be minted.
    """

    links: List[SpectatorLinkView]
    relay_available: bool


class SpectatorLinkRevoked(BaseModel):
    """What a revoke answers.

    Attributes:
      id: the link that was revoked. Its relay watchers are closed when
        the publisher's next ``links`` frame leaves it out, within
        ``relay.refresh_seconds``.
    """

    id: str


def _view(link: SpectatorLink, url: Optional[str] = None) -> SpectatorLinkView:
    return SpectatorLinkView(
        id=link.id,
        session_id=link.session_id,
        label=link.label,
        created_at=iso_utc(link.created_at) or "",
        expires_at=iso_utc(link.expires_at) or "",
        url=url,
    )


def _share_url(viewer_base: str, link: SpectatorLink, token: str) -> str:
    return f"{viewer_base}/s/{link.id}#{share_fragment(token, link.e2ee)}"


def _relay(request: Request) -> Optional[Any]:
    return getattr(request.app.state, "relay", None)


def _relay_unavailable(reason: str) -> HTTPException:
    logger.warning("spectator_link_refused_relay_unavailable", reason=reason)
    return HTTPException(
        status_code=503, detail={"code": "relay_unavailable", "reason": reason}
    )


def _store(request: Request):
    store = getattr(request.app.state, "spectator_links", None)
    if store is None:
        raise HTTPException(
            status_code=503, detail="spectator links are not available"
        )
    return store


def _known_session(request: Request, session_id: str) -> None:
    services = getattr(request.app.state, "services", None)
    registry = getattr(services, "registry", None) if services else None
    if registry is None:
        raise HTTPException(status_code=503, detail="no session registry")
    if session_id not in registry.sessions:
        raise HTTPException(status_code=404, detail="unknown session")


def _validated_ttl(requested: Optional[int]) -> int:
    if requested is None:
        return DEFAULT_TTL_SECONDS
    try:
        ttl = int(requested)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="ttl_seconds must be a number")
    if ttl < MIN_TTL_SECONDS or ttl > MAX_TTL_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"ttl_seconds must be between {MIN_TTL_SECONDS} and "
                f"{MAX_TTL_SECONDS}"
            ),
        )
    return ttl


@router.post(
    "/sessions/{session_id}/spectator-links",
    response_model=SpectatorLinkMinted,
    dependencies=[Depends(require_auth), Depends(account_gates.require_account("share_link"))],
)
async def mint_spectator_link(
    request: Request, session_id: str, body: Optional[SpectatorLinkRequest] = None
) -> SpectatorLinkMinted:
    """Create one read-only share of one live session.
    """
    store = _store(request)
    _known_session(request, session_id)
    payload = body or SpectatorLinkRequest()
    ttl = _validated_ttl(payload.ttl_seconds)
    lifecycle = _relay(request)
    if lifecycle is None:
        raise _relay_unavailable(NOT_RUNNING)
    try:
        async with lifecycle.connected() as publisher:
            return await _mint_on(publisher, store, session_id, ttl, payload.label)
    except RelayUnavailable as exc:
        raise _relay_unavailable(exc.reason) from None


async def _mint_on(
    publisher: Any, store: Any, session_id: str, ttl: int, label: Optional[str]
) -> SpectatorLinkMinted:
    try:
        identity = publisher.new_link_identity()
    except RelayAuthError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "relay_unavailable", "reason": exc.kind}) from None
    try:
        minted = await store.mint(session_id, ttl, label, identity=identity)
    except LinkKeysUnavailableError as exc:
        logger.error("spectator_link_key_not_kept", session_id=session_id)
        raise HTTPException(status_code=503, detail={
            "code": "relay_unavailable", "reason": str(exc)}) from None
    publisher.poke()
    url = _share_url(publisher.viewer_base, minted.link, minted.token)
    logger.info(
        "spectator_link_created",
        link_id=minted.link.id,
        session_id=session_id,
        ttl_seconds=ttl,
        replaced=list(minted.replaced),
    )
    return SpectatorLinkMinted(
        id=minted.link.id,
        url=url,
        expires_at=iso_utc(minted.link.expires_at) or "",
    )


@router.get(
    "/sessions/{session_id}/spectator-links",
    response_model=SpectatorLinkList,
    dependencies=[Depends(require_auth)],
)
async def list_spectator_links(
    request: Request, session_id: str
) -> SpectatorLinkList:
    """Every live share on one session, each with its full link.

    Description: live means not revoked and not expired, because the
      list exists to be revoked FROM and a dead link is not a thing to
      revoke. It does not validate the session: a link on a session that
      has since gone is exactly what an owner wants to see and end.

      THE URL IS BUILT ONLY FROM ``live_token``, which re-checks that the
      link is live, so a link that dies between the two reads is listed
      with no url rather than a dead one. The base is the running
      publisher's, connected or not: the link's address does not change
      while the relay reconnects. A live link always has a running
      publisher (boot starts one for surviving links, and only the last
      link going stops it). NOTHING HERE LOGS THE URL.
    Inputs: request; session_id (str).
    Output: SpectatorLinkList.
    Example: GET /api/v1/sessions/ses_1/spectator-links
    """
    store = _store(request)
    links = await store.list_for_session(session_id)
    lifecycle = _relay(request)
    publisher = None if lifecycle is None else lifecycle.publisher
    views = []
    for link in links:
        token = await store.live_token(link.id) if publisher is not None else None
        url = _share_url(publisher.viewer_base, link, token) if token else None
        views.append(_view(link, url))
    return SpectatorLinkList(
        links=views,
        relay_available=lifecycle is not None and lifecycle.available,
    )


@router.delete(
    "/sessions/{session_id}/spectator-links/{link_id}",
    response_model=SpectatorLinkRevoked,
    dependencies=[Depends(require_auth)],
)
async def revoke_spectator_link(
    request: Request, session_id: str, link_id: str
) -> SpectatorLinkRevoked:
    """End one share, and disconnect whoever is watching through it.

      THE SESSION IN THE PATH IS CHECKED AGAINST THE LINK, so a link id
      guessed or copied from another session cannot be revoked through
      this session's url. It is a 404 rather than a 403: the caller is
      authenticated either way, and there is nothing at that address.
    Inputs: request; session_id (str); link_id (str).
    Output: SpectatorLinkRevoked.
    Example: DELETE /api/v1/sessions/ses_1/spectator-links/ab12
    """
    store = _store(request)
    link = await store.get(link_id)
    if link is None or link.session_id != session_id:
        raise HTTPException(status_code=404, detail="unknown spectator link")

    await store.revoke(link_id)
    notify_revoked(_relay(request))
    logger.info(
        "spectator_link_revoke_requested", link_id=link_id, session_id=session_id
    )
    return SpectatorLinkRevoked(id=link_id)


class SpectatorLinksAll(BaseModel):
    """Every live share on the install, with no token or url.

    Attributes:
      links: the live shares across all sessions, newest first.
    """

    links: List[SpectatorLinkView]


class SpectatorLinksRevokedAll(BaseModel):
    """What the revoke-everything route answers.

    Attributes:
      ids: the links that were live and are now revoked (empty when none were).
    """

    ids: List[str]


@router.get(
    "/spectator-links",
    response_model=SpectatorLinksAll,
    dependencies=[Depends(require_auth)],
)
async def list_all_spectator_links(request: Request) -> SpectatorLinksAll:
    store = _store(request)
    return SpectatorLinksAll(links=[_view(link) for link in await store.list_live()])


@router.delete(
    "/spectator-links",
    response_model=SpectatorLinksRevokedAll,
    dependencies=[Depends(require_auth)],
)
async def revoke_all_spectator_links(request: Request) -> SpectatorLinksRevokedAll:
    """End every live share on the install at once, and disconnect whoever is watching through them.

    Description: the same revoke as the single-link route (the store marks each row, the publisher is poked, the last link
      going closes the connection), over every live link. Works with the share plugin switched off or removed: the tokens
      are core's, so the way to end them stays core's too. Idempotent: a second call finds nothing live and answers an
      empty list.
    Inputs: request. Output: SpectatorLinksRevokedAll.
    Example: DELETE /api/v1/spectator-links
    """
    ended = await revoke_all_live(_store(request), _relay(request))
    return SpectatorLinksRevokedAll(ids=[link.id for link in ended])
