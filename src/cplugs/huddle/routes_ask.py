
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.cplugs.huddle import inbox_stuck_answer, service
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.roles import gone, unstick
from src.cplugs.huddle.routes import Ctx, decide_card, router, run_store
from src.cplugs.sdk import CplugContext


class AnswerRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    answers: Dict[str, Any]
    ack_through: Optional[StrictInt] = Field(None, ge=0)


@router.get("/questions/{message_id}")
async def get_question(message_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The question the form draws (404 for a message that is not a question). Output: the read dict."""
    return await run_store(lambda: AnswerWriter(service.store(ctx)).read(message_id))


@router.post("/questions/{message_id}/answer")
async def post_answer(message_id: int, body: AnswerRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    posted = await run_store(lambda: AnswerWriter(service.store(ctx)).submit(message_id, body.answers, body.ack_through))
    if posted.get("replayed"):
        return posted
    await decide_card(ctx, posted["item"], "answer", f"huddle:msg:{posted['message']['id']}", posted["message"]["text"])
    await unstick.after_answer(ctx, run_store, posted)
    await inbox_stuck_answer.after_answer(ctx, run_store, posted)
    await gone.apply_answer(ctx, posted)
    return {k: v for k, v in posted.items() if k != "carnivore"}
