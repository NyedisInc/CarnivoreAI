
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Union

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_hosted_routes import _hosted, _relay
from src.api.catalog_publish_routes import _SUBMISSION_ID
from src.api.catalog_rating_routes import _bearer
from src.core.catalog import submission_rules, submissions_watch
from src.cplugs.host import install_gates
from src.models.catalog_publish_author import (
    AppealRequest,
    LimitsResponse,
    RulesKind,
    RulesResponse,
    SubmissionActionResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])

_POLICY_PATH = Path(__file__).resolve().parents[1] / "schemas" / "extensions" / "warez" / "policy.json"

_TAB_POLICY_KINDS = {
    "skills": ("skill",),
    "themes": ("theme",),
    "mods": ("mod",),
    "plugins": ("claude-code-plugin", "cplug"),
}

_HERO_CAPS: Dict[str, Union[int, float]] = {
    "hero_max_bytes": 512 * 1024,
    "hero_min_width": 1200,
    "hero_min_height": 500,
    "hero_max_side": 8192,
    "hero_max_pixels": 16_000_000,
    "hero_ratio_min": 1.5,
    "hero_ratio_max": 3.0,
}


def _check_id(submission_id: str) -> None:
    if not _SUBMISSION_ID.fullmatch(submission_id):
        raise HTTPException(status_code=404, detail="no such submission")


def _policy_kinds() -> Dict[str, str]:
    try:
        kinds = json.loads(_POLICY_PATH.read_text(encoding="utf-8")).get("kinds")
    except (OSError, ValueError) as exc:
        logger.warning("publish_policy_unreadable", error=str(exc))
        raise HTTPException(status_code=503, detail={"code": "policy_unreadable", "detail": "the publish rules cannot be read"}) from exc
    if not isinstance(kinds, dict):
        raise HTTPException(status_code=503, detail={"code": "policy_unreadable", "detail": "the publish rules cannot be read"})
    return kinds


_KIND_CAPS = {
    "skill": (submission_rules.MAX_MEMBERS, submission_rules.MAX_FILE_BYTES, submission_rules.MAX_SUBMISSION_BYTES),
    "theme": (32, 512 * 1024, 1024 * 1024),
    "plugin": (500, submission_rules.MAX_FILE_BYTES, 1024 * 1024),
    "mod": (200, submission_rules.MAX_FILE_BYTES, 1024 * 1024),
    "cplug": (install_gates.MAX_MEMBERS, install_gates.MAX_FILE_BYTES, install_gates.MAX_TOTAL_BYTES),
}


def _kind_caps() -> Dict[str, Union[int, float]]:
    caps: Dict[str, Union[int, float]] = {}
    for kind, (members, file_bytes, total_bytes) in _KIND_CAPS.items():
        caps[f"{kind}_members"] = members
        caps[f"{kind}_file_bytes"] = file_bytes
        caps[f"{kind}_total_bytes"] = total_bytes
    return caps


@router.post(
    "/catalog/submissions/{submission_id}/appeal",
    response_model=SubmissionActionResponse,
    dependencies=[Depends(require_auth)],
)
async def appeal_submission(submission_id: str, body: AppealRequest, request: Request) -> SubmissionActionResponse:
    """Appeal one of your rejected submissions: relays hosted ``POST /v1/submissions/{id}/appeal``.

    Raises: 404 not a submission id; the host's 409 ``appeal_limit``, ``not_rejected`` or ``kind_closed``, 429;
        403 not signed in; 502 catalog host unreachable.
    """
    _check_id(submission_id)
    answer = await _hosted(
        request, "POST", f"/submissions/{submission_id}/appeal", json_body={"text": body.text}, bearer=await _bearer(request)
    )
    result = _relay(answer)
    submissions_watch.after_write(request)
    return SubmissionActionResponse(**{k: result.get(k) for k in SubmissionActionResponse.model_fields if k in result})


@router.post(
    "/catalog/submissions/{submission_id}/withdraw",
    response_model=SubmissionActionResponse,
    dependencies=[Depends(require_auth)],
)
async def withdraw_submission(submission_id: str, request: Request) -> SubmissionActionResponse:
    """Take back a send that is still pending or approved: relays hosted ``POST /v1/submissions/{id}/withdraw``.

    Raises: 404 not a submission id; the host's 409 ``not_withdrawable``; 403 not signed in; 502 catalog host unreachable.
    """
    _check_id(submission_id)
    answer = await _hosted(request, "POST", f"/submissions/{submission_id}/withdraw", bearer=await _bearer(request))
    result = _relay(answer)
    submissions_watch.after_write(request)
    return SubmissionActionResponse(**{k: result.get(k) for k in SubmissionActionResponse.model_fields if k in result})


@router.get(
    "/catalog/submissions/limits",
    response_model=LimitsResponse,
    dependencies=[Depends(require_auth)],
)
async def submission_limits(request: Request) -> LimitsResponse:
    """What this account may still send today: relays hosted ``GET /v1/submissions/limits``.

    Raises: 403 not signed in; 429 the host's read limit; 502 catalog host unreachable.
    """
    answer = await _hosted(request, "GET", "/submissions/limits", bearer=await _bearer(request))
    result = _relay(answer)
    return LimitsResponse(**{k: result[k] for k in LimitsResponse.model_fields if result.get(k) is not None})


@router.get(
    "/catalog/publish/rules",
    response_model=RulesResponse,
    dependencies=[Depends(require_auth)],
)
async def publish_rules(request: Request) -> RulesResponse:
    """Which page tabs the front door takes, the hero image rules and the per-kind caps. Asks nobody.

    Raises: 503 ``policy_unreadable``.
    """
    policy = _policy_kinds()
    kinds: List[RulesKind] = [
        RulesKind(kind=tab, open=any(policy.get(name) == "open" for name in names))
        for tab, names in _TAB_POLICY_KINDS.items()
    ]
    return RulesResponse(kinds=kinds, caps={**_HERO_CAPS, **_kind_caps()})
