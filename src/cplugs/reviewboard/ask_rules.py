
from __future__ import annotations

from typing import List, Sequence

from src.cplugs.reviewboard.schema import Anchor, Prompt


def anchor_problems(where: str, anchors: Sequence[Anchor]) -> List[str]:
    ids = [a.id for a in anchors]
    return [f"{where}.anchors: an anchor id is used twice"] if len(set(ids)) != len(ids) else []


def prompt_problems(where: str, prompts: Sequence[Prompt], anchors: Sequence[Anchor]) -> List[str]:
    out: List[str] = []
    declared = [a.id for a in anchors]
    prompt_ids = [p.id for p in prompts]
    if len(set(prompt_ids)) != len(prompt_ids):
        out.append(f"{where}.prompts: a prompt id is used twice")
    for p in prompts:
        if p.kind in ("choice", "multi"):
            options = [o.id for o in p.options or []]
            if not options or len(set(options)) != len(options):
                out.append(f"{where}.prompts.{p.id}: a {p.kind} prompt needs options with distinct ids")
        elif p.options is not None:
            out.append(f"{where}.prompts.{p.id}: a {p.kind} prompt has no options")
        if p.anchor is not None and p.anchor not in declared:
            out.append(f"{where}.prompts.{p.id}: anchor {p.anchor} is not declared in this revision")
    return out
