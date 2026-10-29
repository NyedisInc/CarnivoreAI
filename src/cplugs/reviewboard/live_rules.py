
from __future__ import annotations

from typing import List

from src.cplugs.reviewboard import ask_rules
from src.cplugs.reviewboard.schema import BASE_SCHEMA_VERSION, Sidecar

MAIN_VIEW = "main"


def draft_file(view_id: str) -> str:
    return "draft.html" if view_id == MAIN_VIEW else f"draft--{view_id}.html"


def uses_version_two(sidecar: Sidecar) -> bool:
    return sidecar.live is not None or any(r.milestone is not None or r.inline_picks is not None for r in sidecar.revisions)


def problems(sidecar: Sidecar) -> List[str]:
    out: List[str] = []
    if sidecar.schema_version == BASE_SCHEMA_VERSION and uses_version_two(sidecar):
        out.append("schema_version: a live session, a milestone or inline picks need schema_version 2")
    live = sidecar.live
    if live is None:
        return out
    draft = live.draft
    ids = [v.id for v in draft.views]
    if ids[0] != MAIN_VIEW:
        out.append(f"live.draft.views: the first view must be '{MAIN_VIEW}'")
    if len(set(ids)) != len(ids):
        out.append("live.draft.views: a view id is used twice")
    for v in draft.views:
        if v.file != draft_file(v.id):
            out.append(f"live.draft.views: {v.file} must be {draft_file(v.id)} (the draft's own file for view {v.id})")
    out += ask_rules.anchor_problems("live.draft", draft.anchors)
    out += ask_rules.prompt_problems("live.draft", draft.prompts, draft.anchors)
    numbers = [s.n for s in live.sends]
    if numbers != sorted(set(numbers)):
        out.append("live.sends: sends run in order with no repeat")
    if numbers and live.sends_total < numbers[-1]:
        out.append("live.sends_total: smaller than the newest send's number")
    return out
