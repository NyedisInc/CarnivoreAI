
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.cplugs.huddle import answers as answer_wire, inbox_stuck_answer, service, swarm_forms
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.roles import gone, unstick
from src.cplugs.huddle.routes import Ctx, decide_card, router, run_store
from src.cplugs.sdk import CplugContext


class AnswerRequest(BaseModel):
    """Joe's submit: an answer per question id (the shapes of ``answers.py``)."""

    model_config = ConfigDict(extra="forbid")
    answers: Dict[str, Any]
    ack_through: Optional[StrictInt] = Field(None, ge=0)


@router.get("/questions/{message_id}")
async def get_question(message_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The question the form draws (404 for a message that is not a question). Output: the read dict."""
    return await run_store(lambda: AnswerWriter(service.store(ctx)).read(message_id))


@router.post("/questions/{message_id}/answer")
async def post_answer(message_id: int, body: AnswerRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Joe's submit of a form ask, as joe. A submit on a Swarm card tells the Swarm with the answer's text. Output: {item, message}, plus ``replayed`` True when the same answers already stood (a retry; nothing ran twice)."""
    writer = AnswerWriter(service.store(ctx))
    asked = await run_store(lambda: writer.read(message_id))
    answers = await run_store(lambda: swarm_forms.resolve_files(ctx.storage, asked["item"], body.answers))
    posted = await run_store(lambda: writer.submit(message_id, answers, body.ack_through))
    if posted.get("replayed"):
        return posted
    note, structured = posted["message"]["text"], None
    if (posted["item"].get("swarm_ref") or "").startswith("question:"):
        questions = asked["ask"]["questions"]
        note, structured = swarm_forms.delivery(questions, answer_wire.validate(questions, answers))
    await decide_card(ctx, posted["item"], "answer", f"huddle:msg:{posted['message']['id']}", note, structured=structured)
    await unstick.after_answer(ctx, run_store, posted)
    await inbox_stuck_answer.after_answer(ctx, run_store, posted)
    await gone.apply_answer(ctx, posted)
    return {k: v for k, v in posted.items() if k != "carnivore"}
