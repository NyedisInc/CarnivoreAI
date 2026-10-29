
from __future__ import annotations

import json
from typing import Any, List

from src.cplugs.reviewboard.schema import Answer, Prompt, Revision, Round

LIMIT = 3900
CUT_MARK = "\n... (the rest is on the board)"


def _picked(prompt: Prompt, answer: Answer) -> str:
    if prompt.kind in ("choice", "multi"):
        labels = {o.id: o.label for o in prompt.options or []}
        return ", ".join(labels.get(o, o) for o in answer.options or [])
    if prompt.kind == "check":
        return "yes" if answer.checked else "no"
    return (answer.text or "").strip()


def read_line(slug: str, round_: Round) -> str:
    return "read it: task_manager_board_get " + json.dumps({"board": slug, "since_round": round_.n - 1})


NUDGE_NOTE_MAX = 300


def payload_nudge(title: str, slug: str, revision: Revision, round_: Round) -> str:
    save = f", save {round_.save}" if round_.save else ""
    lines = [f"review the payload: round {round_.id} on board {slug} ({revision.id}{save}, {title})"]
    note = round_.note.strip()
    if note:
        lines.append("note: " + (note if len(note) <= NUDGE_NOTE_MAX else note[: NUDGE_NOTE_MAX - 3].rstrip() + "..."))
    lines.append(read_line(slug, round_))
    return "\n".join(lines)


def answer_lines(asked: Any, sent: Any) -> List[str]:
    prompts = {p.id: p for p in asked.prompts}
    anchors = {a.id: a.label for a in asked.anchors}
    lines: List[str] = []
    for answer in sent.answers:
        prompt = prompts[answer.prompt]
        said = _picked(prompt, answer)
        lines.append(f"{prompt.label}: {said}" if said else prompt.label)
        if answer.note.strip():
            lines.append(f"  note on {prompt.label}: {answer.note.strip()}")
    for pinned in sent.anchor_notes:
        lines.append(f"{anchors.get(pinned.anchor, pinned.anchor)}: {pinned.text.strip()}")
    if sent.note.strip():
        lines.append(f"note: {sent.note.strip()}")
    if sent.unanswered:
        lines.append("skipped: " + ", ".join(prompts[p].label for p in sent.unanswered if p in prompts))
    return lines


def summary(title: str, slug: str, revision: Revision, round_: Round) -> str:
    if round_.payload is not None:
        return payload_nudge(title, slug, revision, round_)
    context = ", ".join(x for x in (round_.context.theme, f"{round_.context.width}px" if round_.context.width else None) if x)
    head = f"review round {round_.n} on {revision.id} ({title})" + (f", {context}" if context else "")
    lines: List[str] = [head, *answer_lines(revision, round_)]
    tail = "\n" + read_line(slug, round_)
    body = "\n".join(lines)
    room = LIMIT - len(tail)
    return (body if len(body) <= room else body[: room - len(CUT_MARK)].rstrip() + CUT_MARK) + tail
