
from __future__ import annotations

from typing import Dict, List, Set

from src.cplugs.reviewboard import ask_rules, live_rules
from src.cplugs.reviewboard.layers import rules as layer_rules
from src.cplugs.reviewboard.schema import MAX_ROUND_NOTES, Revision, Round, Sidecar

MAIN_VIEW = "main"
LEGACY_EXT = "legacy"


def view_file(n: int, view_id: str) -> str:
    return f"r{n:03d}.html" if view_id == MAIN_VIEW else f"r{n:03d}--{view_id}.html"


def _file_revision(name: str) -> int:
    return int(name[1:].split("--", 1)[0].split(".", 1)[0])


def _reconstructed(rev: Revision) -> bool:
    legacy = rev.ext.get(LEGACY_EXT)
    return legacy is not None and (legacy.model_extra or {}).get("reconstructed") is True


def _revision_problems(rev: Revision, index: int, total: int) -> List[str]:
    where = f"revisions[{index}]"
    out: List[str] = []
    if rev.n != index + 1 or rev.id != f"r{index + 1}":
        out.append(f"{where}: expected id r{index + 1} and n {index + 1} (revisions run r1, r2, ... with no gap)")
    view_ids = [v.id for v in rev.views]
    if view_ids[0] != MAIN_VIEW:
        out.append(f"{where}.views: the first view must be '{MAIN_VIEW}'")
    if len(set(view_ids)) != len(view_ids):
        out.append(f"{where}.views: a view id is used twice")
    borrows = _reconstructed(rev)
    for v in rev.views:
        number = _file_revision(v.file)
        own = v.file == view_file(rev.n, v.id)
        later = borrows and rev.n < number <= total and v.file == view_file(number, v.id)
        if not (own or later):
            out.append(f"{where}.views: {v.file} must be {view_file(rev.n, v.id)} (revision {rev.n}'s own file for view {v.id}; "
                       "only a revision marked ext.legacy.reconstructed may share a later revision's file)")
    anchors = [a.id for a in rev.anchors]
    out += ask_rules.anchor_problems(where, rev.anchors)
    out += _save_problems(rev, where)
    out += _layer_problems(rev, where, anchors)
    out += ask_rules.prompt_problems(where, rev.prompts, rev.anchors)
    return out


def _layer_problems(rev: Revision, where: str, anchors: List[str]) -> List[str]:
    """Problems with a revision's layer (#1832): a layer revision is payload mode, carries no prompts (one layer at a time), and its items check out.

    Inputs: rev; where; anchors (the ids the revision declares). Output: list (empty for a revision with no layer).
    """
    if rev.layer is None:
        return []
    out: List[str] = []
    if not rev.payload_mode:
        out.append(f"{where}.layer: a layer revision is payload_mode (the layer posts its answers as a payload)")
    if rev.prompts:
        out.append(f"{where}.prompts: a layer revision carries no prompts (one layer at a time)")
    return out + layer_rules.problems(rev.layer, anchors, f"{where}.layer")


def _save_problems(rev: Revision, where: str) -> List[str]:
    out: List[str] = []
    if rev.draft is not None and not rev.payload_mode:
        out.append(f"{where}.draft: only a revision with payload_mode holds a draft")
    if not rev.saves:
        return out
    if not rev.payload_mode:
        out.append(f"{where}.saves: only a revision with payload_mode holds saves")
    for i, save in enumerate(rev.saves):
        if save.n != i + 1:
            out.append(f"{where}.saves[{i}]: expected n {i + 1} (saves run 1, 2, ... with no gap)")
    return out


def _payload_round_problems(rnd: Round, where: str, rev: Revision) -> List[str]:
    if rnd.payload is None:
        return [f"{where}: save and diff belong to a round with a payload"] if rnd.save is not None or rnd.diff is not None else []
    out: List[str] = []
    if not rev.payload_mode:
        out.append(f"{where}.payload: {rev.id} does not hold its own answers (payload_mode)")
    if rnd.answers or rnd.anchor_notes or rnd.unanswered:
        out.append(f"{where}: a payload round carries no prompt answers, anchor notes or skipped prompts")
    made = next((s for s in rev.saves or [] if s.n == rnd.save), None)
    if made is None:
        out.append(f"{where}.save: {rnd.save} is not a save of {rev.id}")
    elif made.payload != rnd.payload:
        out.append(f"{where}.payload: differs from {rev.id}'s save {rnd.save}, which this send made")
    return out


def answer_problems(rnd: Round, where: str, rev: Revision) -> List[str]:
    out: List[str] = []
    prompts = {p.id: p for p in rev.prompts}
    answered: Set[str] = set()
    for a in rnd.answers:
        prompt = prompts.get(a.prompt)
        if prompt is None:
            out.append(f"{where}.answers: prompt {a.prompt} is not a prompt of {rev.id}")
            continue
        if a.prompt in answered:
            out.append(f"{where}.answers: prompt {a.prompt} is answered twice")
        answered.add(a.prompt)
        valid = {o.id for o in prompt.options or []}
        if prompt.kind in ("choice", "multi"):
            picks = a.options or []
            count_ok = len(picks) == 1 if prompt.kind == "choice" else len(picks) >= 1
            if not count_ok or len(set(picks)) != len(picks) or not set(picks) <= valid or a.checked is not None or a.text is not None:
                out.append(f"{where}.answers.{a.prompt}: a {prompt.kind} answer picks {'one' if prompt.kind == 'choice' else 'one or more'} of its options and nothing else")
        elif prompt.kind == "check":
            if a.checked is None or a.options is not None or a.text is not None:
                out.append(f"{where}.answers.{a.prompt}: a check answer carries checked and nothing else")
        elif a.text is None or not a.text.strip() or a.options is not None or a.checked is not None:
            out.append(f"{where}.answers.{a.prompt}: a question answer carries non-empty text and nothing else")
    declared = {x.id for x in rev.anchors}
    for note in rnd.anchor_notes:
        if note.anchor not in declared:
            out.append(f"{where}.anchor_notes: anchor {note.anchor} is not declared in {rev.id}")
    for skipped in rnd.unanswered:
        if skipped not in prompts or skipped in answered:
            out.append(f"{where}.unanswered: {skipped} is not an unanswered prompt of {rev.id}")
    total = len(rnd.note) + sum(len(a.note) for a in rnd.answers) + sum(len(n.text) for n in rnd.anchor_notes)
    if total > MAX_ROUND_NOTES:
        out.append(f"{where}: its notes hold {total} characters; the limit for one round is {MAX_ROUND_NOTES}")
    return out


def _round_problems(rnd: Round, index: int, revisions: Dict[str, Revision]) -> List[str]:
    where = f"rounds[{index}]"
    out: List[str] = []
    if rnd.n != index + 1 or rnd.id != f"n{index + 1}":
        out.append(f"{where}: expected id n{index + 1} and n {index + 1} (rounds run n1, n2, ... with no gap)")
    rev = revisions.get(rnd.revision)
    if rev is None:
        out.append(f"{where}: revision {rnd.revision} does not exist")
    else:
        out += answer_problems(rnd, where, rev)
        out += _payload_round_problems(rnd, where, rev)
        if rnd.context.view is not None and rnd.context.view not in {v.id for v in rev.views}:
            out.append(f"{where}.context.view: {rnd.context.view} is not a view of {rev.id}")
    d = rnd.delivery
    if d.state == "posted" and (d.item_id is None or d.at is None):
        out.append(f"{where}.delivery: a posted round names the item and the time it was posted")
    if d.state == "undelivered" and d.reason is None:
        out.append(f"{where}.delivery: an undelivered round says why")
    return out


def check(sidecar: Sidecar) -> List[str]:
    out: List[str] = []
    total = len(sidecar.revisions)
    for i, rev in enumerate(sidecar.revisions):
        out += _revision_problems(rev, i, total)
    out += live_rules.problems(sidecar)
    revisions = {r.id: r for r in sidecar.revisions}
    rounds_by_id = {r.id: r for r in sidecar.rounds}
    for i, rev in enumerate(sidecar.revisions):
        if rev.answers_round is None:
            continue
        answered = rounds_by_id.get(rev.answers_round)
        if answered is None or answered.revision not in revisions or revisions[answered.revision].n >= rev.n:
            out.append(f"revisions[{i}].answers_round: {rev.answers_round} is not a round sent on an earlier revision")
    client_ids: Set[str] = set()
    for i, rnd in enumerate(sidecar.rounds):
        out += _round_problems(rnd, i, revisions)
        if rnd.client_round_id in client_ids:
            out.append(f"rounds[{i}].client_round_id: used by an earlier round (one send is one round)")
        client_ids.add(rnd.client_round_id)
    return out
