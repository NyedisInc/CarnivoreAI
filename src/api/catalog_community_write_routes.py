
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.catalog_community_routes import safe_segment
from src.api.catalog_hosted_routes import _hosted, _relay, _safe_item_id
from src.api.catalog_rating_routes import _bearer
from src.models.catalog_community import (
    CommentDeleteResponse,
    CommentEditRequest,
    CommentPostRequest,
    CommentWriteResponse,
    MailPreferenceRequest,
    MailPreferenceResponse,
    ProfileEditRequest,
    ProfileResponse,
    ReportRequest,
    ReportResponse,
)

router = APIRouter(tags=["catalog"])


async def _send(
    request: Request, method: str, path: str, body: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    bearer = await _bearer(request)
    answer = await _hosted(request, method, path, json_body=body, bearer=bearer)
    return _relay(answer)


@router.post(
    "/catalog/items/{item_id:path}/comments",
    response_model=CommentWriteResponse,
    status_code=201,
    dependencies=[Depends(require_auth)],
)
async def catalog_post_comment(
    request: Request, item_id: str, body: CommentPostRequest
) -> CommentWriteResponse:
    """Post a comment, or a reply when ``parent_id`` is set (one reply level).

    Raises: 400 ``comment_invalid`` / ``reply_depth`` (relayed); 403
    ``unauthorized`` (signed out, nothing sent) or the registration gate
    (``handle_required`` and friends, relayed with its code); 404
    ``unknown_item`` / ``parent_not_found``; 429 rate limited; 502.
    """
    safe = _safe_item_id(item_id)
    payload = body.model_dump(exclude_none=True)
    return CommentWriteResponse(**await _send(request, "POST", f"/items/{safe}/comments", payload))


@router.put(
    "/catalog/items/{item_id:path}/comments/{comment_id}",
    response_model=CommentWriteResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_edit_comment(
    request: Request, item_id: str, comment_id: str, body: CommentEditRequest
) -> CommentWriteResponse:
    """Edit your own comment (15 minutes, 5 edits, re-gated by moderation).

    Raises: 400 ``comment_invalid``; 403 ``unauthorized`` or a gate code;
    404 ``comment_not_found`` (also for someone else's); 409; 502.
    """
    path = f"/items/{_safe_item_id(item_id)}/comments/{safe_segment(comment_id)}"
    return CommentWriteResponse(**await _send(request, "PUT", path, body.model_dump()))


@router.delete(
    "/catalog/items/{item_id:path}/comments/{comment_id}",
    response_model=CommentDeleteResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_delete_comment(
    request: Request, item_id: str, comment_id: str
) -> CommentDeleteResponse:
    """Soft delete your own comment (the body is wiped upstream).

    Raises: 403 ``unauthorized`` or a gate code; 404 ``comment_not_found``;
    409 ``comment_locked``; 502.
    """
    path = f"/items/{_safe_item_id(item_id)}/comments/{safe_segment(comment_id)}"
    return CommentDeleteResponse(**await _send(request, "DELETE", path))


@router.post(
    "/catalog/reports",
    response_model=ReportResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_report(request: Request, body: ReportRequest) -> ReportResponse:
    """Report a comment, review or item. One report per account per target.

    Raises: 400 (relayed validation); 403 ``unauthorized`` or a gate
    code; 404; 429 (10 a day); 502.
    """
    _safe_item_id(body.item_id)
    return ReportResponse(**await _send(request, "POST", "/reports", body.model_dump(exclude_none=True)))


@router.put(
    "/catalog/me/profile",
    response_model=ProfileResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_edit_profile(request: Request, body: ProfileEditRequest) -> ProfileResponse:
    """Edit your own profile bio and links; only the fields sent change.

    Raises: 400 ``bio_invalid`` / ``link_invalid`` / ``bad_request``;
    403 ``unauthorized`` or ``handle_required``; 502.
    """
    payload = body.model_dump(exclude_unset=True)
    return ProfileResponse(**await _send(request, "PUT", "/me/profile", payload))


@router.put(
    "/catalog/me/mail-preference",
    response_model=MailPreferenceResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_mail_preference(
    request: Request, body: MailPreferenceRequest
) -> MailPreferenceResponse:
    """Opt in or out of reply notice mail.

    Raises: 403 ``unauthorized``; 404 ``unknown_user``; 502.
    """
    return MailPreferenceResponse(
        **await _send(request, "PUT", "/mail/preference", body.model_dump())
    )
