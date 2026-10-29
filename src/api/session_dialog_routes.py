
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.approvals.answer import AnswerRefused, Choice
from src.core.approvals.answer_all import QuestionAnswer
from src.core.approvals.ask_questions import served_fields
from src.core.approvals.deliver import SOURCE_OWNER, SOURCE_OWNER_BANNER, deliver_answer, deliver_answers
from src.models.dialogs import (
    DialogAnswerRequest, DialogAnswerResponse, DialogResponse, QuestionsAnswerRequest, QuestionsAnswerResponse)

logger = structlog.get_logger()
router = APIRouter()


def _source(claimed: Optional[str]) -> str:
    return SOURCE_OWNER_BANNER if claimed == "owner_banner" else SOURCE_OWNER


def _refuse(session_id: str, reason: str) -> HTTPException:
    logger.info("session_dialog_refused", session_id=session_id, reason=reason)
    return HTTPException(status_code=409, detail={"reason": reason})


async def _info(request: Request, session_id: str):
    manager = request.app.state.session_manager
    refuse_remote(manager, session_id, "answering a dialog")
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    return manager, info


@router.get("/sessions/{session_id}/dialog", response_model=DialogResponse,
            dependencies=[Depends(require_peer_sessions)])
async def get_dialog(request: Request, session_id: str) -> DialogResponse:
    """The open dialog from the latest watcher observation, or ``{"dialog": null}``.

    Inputs: session_id (str) - either id shape. Output: DialogResponse. No pane is captured. A live
      AskUserQuestion also carries ``questions`` (every question with option descriptions, read from the
      conversation transcript), ``questions_fingerprint`` and ``questions_state`` (``approvals.md``).
    Example: GET /api/v1/sessions/ses_abc/dialog
    """
    _, info = await _info(request, session_id)
    watcher = getattr(request.app.state, "attention_watcher", None)
    observation = watcher.observation_for(info.session.id) if watcher is not None else None
    dialog = observation.evidence.dialog if observation is not None else None
    if dialog is None:
        return DialogResponse(dialog=None)
    return DialogResponse(dialog={**dialog.to_dict(), **await served_fields(info, watcher, dialog)})


@router.post("/sessions/{session_id}/dialog/answer", response_model=DialogAnswerResponse,
             dependencies=[Depends(require_peer_sessions)])
async def answer_session_dialog(request: Request, session_id: str,
                                body: DialogAnswerRequest) -> DialogAnswerResponse:
    """Answer the session's open dialog if it is still the one the caller saw.

    Inputs: session_id (str); body (DialogAnswerRequest) - fingerprint plus one choice.
    Output: DialogAnswerResponse. Raises: 404 unknown session; 409 ``{reason}``
      (session_gone, not_running, or any AnswerRefused reason); 422 bad body.
    Example: POST .../dialog/answer {"fingerprint": "<64 hex>", "choice": {"option": "Blue"}, "source": "owner_banner"}
    """
    manager, info = await _info(request, session_id)
    choice = Choice(option=body.choice.option, options=body.choice.options, other=body.choice.other,
                    dismiss=bool(body.choice.dismiss), plain=body.choice.plain)
    try:
        dialog = await deliver_answer(manager=manager, watcher=getattr(request.app.state, "attention_watcher", None),
                                      info=info, fingerprint=body.fingerprint, choice=choice, source=_source(body.source))
    except AnswerRefused as exc:
        raise _refuse(session_id, exc.reason) from exc
    return DialogAnswerResponse(kind=dialog.kind, fingerprint=dialog.fingerprint)


@router.post("/sessions/{session_id}/dialog/answer-all", response_model=QuestionsAnswerResponse,
             dependencies=[Depends(require_peer_sessions)])
async def answer_session_questions(request: Request, session_id: str,
                                   body: QuestionsAnswerRequest) -> QuestionsAnswerResponse:
    """Answer EVERY question of the session's open AskUserQuestion and submit once (issue #1548).
    """
    manager, info = await _info(request, session_id)
    answers = [QuestionAnswer(option=a.option, options=None if a.options is None else tuple(a.options),
                              other=a.other, notes=a.notes) for a in body.answers]
    try:
        via = await deliver_answers(manager=manager, watcher=getattr(request.app.state, "attention_watcher", None),
                                    info=info, questions_fingerprint=body.questions_fingerprint, answers=answers,
                                    source=_source(body.source))
    except AnswerRefused as exc:
        raise _refuse(session_id, exc.reason) from exc
    return QuestionsAnswerResponse(count=len(answers), via=via, questions_fingerprint=body.questions_fingerprint)
