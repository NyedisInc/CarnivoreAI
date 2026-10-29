
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional

from src.cplugs.huddle import actor_log, answers, board, fork as forks, kinds, lane, lineage, review, review_lock, rules
from src.cplugs.huddle.cards import flow, state_log
from src.cplugs.huddle.rules import CLAUDE, JOE, QUESTION, TaskManagerInvalid

HANDOFF_ROOT: Path = Path.home() / ".handoff"
_PENDING = re.compile(r"\.handoff/pending/([A-Za-z0-9][A-Za-z0-9_.-]*?)\.sh\b")
_ONE_LINER = re.compile(r"\.handoff/handoff(?:\s+(?:show|--plain))?\s+([A-Za-z0-9][A-Za-z0-9_.-]*)")
_AGENT_OWN_SQL = "author = 'claude' AND COALESCE(author_key, '') NOT IN (?, ?, ?) AND COALESCE(category, '') = ''"
_SYSTEM_KEYS = (rules.CARNIVORE_KEY, rules.SWARM_KEY, rules.NUDGE_KEY)
WITHDRAWN = "review withdrawn"
STORED_AS_ANSWER_TO = "stored_as_answer_to"
GUARD_NOTE = "owner_guard"
FILES_ONLY_QUOTE = "(the owner's attached files)"


class ReplyPlan(NamedTuple):

    kind: Optional[str]
    quote: Optional[int]
    quote_text: str
    notify: bool
    said: Dict[str, Any]


def _is_form_submit(parts: str) -> bool:
    given = answers.wire(parts or "")
    return given is not None and not given.get("freeform")


def _answers_carnivore(conn: sqlite3.Connection, parts: str) -> bool:
    given = answers.wire(parts or "") or {}
    asked = conn.execute("SELECT author_key, category FROM work_messages WHERE id = ?", (given.get(answers.ANSWERS_TO, 0),)).fetchone()
    return asked is not None and (asked["author_key"] == rules.CARNIVORE_KEY or bool(asked["category"]))


def unanswered_owner_message(conn: sqlite3.Connection, item_id: int) -> Optional[sqlite3.Row]:
    owner = None
    for row in conn.execute("SELECT id, text, parts, created_at FROM work_messages WHERE item_id = ? AND author = ? ORDER BY id DESC", (item_id, JOE)):
        if board.round_wire(row["parts"] or "") is not None:
            return None
        if not _is_form_submit(row["parts"]):
            owner = row
            break
        if not _answers_carnivore(conn, row["parts"]):
            return None
    if owner is None:
        return None
    replied = conn.execute(f"SELECT 1 FROM work_messages WHERE item_id = ? AND {_AGENT_OWN_SQL} AND id > ? AND kind IN (?, ?) LIMIT 1",
                           (item_id, *_SYSTEM_KEYS, owner["id"], kinds.ANSWER, QUESTION)).fetchone()
    if replied is not None:
        return None
    handed = conn.execute("SELECT 1 FROM work_card_events WHERE item_id = ? AND kind = ? AND to_col = ? AND by NOT IN (?, ?) AND at > ? LIMIT 1",
                          (item_id, state_log.KIND, rules.REVIEW, actor_log.by_for(JOE), lineage.CARNIVORE, owner["created_at"])).fetchone()
    return None if handed is not None else owner


def plan_reply(store: Any, item_id: int, kind: Optional[str], notify: bool, *, quote: Optional[int] = None, quote_text: str = "",
               has_files: bool = False) -> ReplyPlan:
    unchanged = ReplyPlan(kind, quote, quote_text, notify, {})
    if kind not in (None, kinds.INFO):
        return unchanged
    with closing(store._read_connection()) as conn:
        owner = unanswered_owner_message(conn, item_id)
    if owner is None:
        return unchanged
    message_id = int(owner["id"])
    if has_files:
        return unchanged._replace(said={GUARD_NOTE: (
            f"stored as info because it attaches files, but the owner's message {message_id} is still unanswered: answer it with "
            f"task_manager_reply kind answer quote {message_id} before you set review")})
    words = str(owner["text"] or "").strip()
    note = (f"stored as an answer to the owner's message {message_id}: an info posted while their newest message is unanswered is an answer "
            ". next time send kind answer with quote yourself")
    if notify:
        note += "; notify was dropped, an answer never marks the item unread"
    return ReplyPlan(kinds.ANSWER, message_id if words else None, "" if words else FILES_ONLY_QUOTE, False,
                     {STORED_AS_ANSWER_TO: message_id, GUARD_NOTE: note})


def handoff_result(name: str, root: Optional[Path] = None) -> Path:
    return (root if root is not None else HANDOFF_ROOT) / "log" / f"{_stem(name)}.result"


def handoff_script(name: str, root: Optional[Path] = None) -> Path:
    return (root if root is not None else HANDOFF_ROOT) / "pending" / f"{_stem(name)}.sh"


def _stem(name: str) -> str:
    return name[:-3] if name.endswith(".sh") else name


def pending_handoffs(texts: Iterable[str], root: Optional[Path] = None) -> List[str]:
    base = root if root is not None else HANDOFF_ROOT
    if not base.is_dir():
        return []
    named = set()
    for text in texts:
        for found in (*_PENDING.findall(text or ""), *_ONE_LINER.findall(text or "")):
            named.add(_stem(found.rstrip(".")))
    return sorted(name for name in named if name and handoff_script(name, base).is_file() and not handoff_result(name, base).exists())


def _review_texts(row: Mapping[str, Any]) -> List[str]:
    return [str(row[name] or "") for name in ("text", *review.FIELDS)]


def _handoff_reason(queued: List[str]) -> str:
    return f"the handoff {', '.join(queued)} has not been run yet (no .result in ~/.handoff/log)"


def review_blockers(conn: sqlite3.Connection, row: Mapping[str, Any]) -> List[str]:
    item_id = int(row["id"])
    reasons: List[str] = []
    owner = unanswered_owner_message(conn, item_id)
    if owner is not None:
        reasons.append(f"the owner's message {owner['id']} is unanswered: answer it with task_manager_reply kind answer quote {owner['id']}")
    asked = conn.execute(f"SELECT id FROM work_messages WHERE item_id = ? AND {_AGENT_OWN_SQL} AND kind = ? AND answered = 0 ORDER BY id",
                         (item_id, *_SYSTEM_KEYS, QUESTION)).fetchall()
    if asked:
        reasons.append(f"your question {', '.join(str(r['id']) for r in asked)} is still open: wait for their answer")
    stuck = review_lock.review_subtasks(conn, item_id)
    if stuck:
        reasons.append(review_lock.subtasks_sentence(stuck, "in review or done") + " (finish each and set it to review)")
    thread = [r["text"] for r in conn.execute("SELECT text FROM work_messages WHERE item_id = ?", (item_id,)).fetchall()]
    queued = pending_handoffs([*_review_texts(row), *thread])
    if queued:
        reasons.append(_handoff_reason(queued))
    return reasons


def _exempt(row: Mapping[str, Any], actor: str, act: Optional[Any], decided: Optional[Any]) -> bool:
    return actor != CLAUDE or act is not None or decided is not None or row["lane"] == lane.SWARM or bool(row["swarm_ref"])


def _refuse(reasons: List[str], stuck: Optional[List[Dict[str, Any]]] = None) -> None:
    if not reasons:
        return
    message = "not ready for review (review means ready to be closed): " + "; ".join(reasons)
    if stuck:
        raise review_lock.locked(stuck, [], message)
    raise TaskManagerInvalid(message)


def check_review(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: Optional[str], actor: str, *,
                 act: Optional[Any] = None, decided: Optional[Any] = None, review_fields: Optional[Mapping[str, Any]] = None) -> None:
    if new_state != rules.REVIEW or _exempt(row, actor, act, decided):
        return
    incoming = {k: v for k, v in (review_fields or {}).items() if k in review.FIELDS}
    if row["state"] == rules.REVIEW:  # already in review
        queued = pending_handoffs([str(v or "") for k, v in incoming.items() if v != row[k]])
        _refuse([_handoff_reason(queued)] if queued else [])
        return
    _refuse(review_blockers(conn, {**{k: row[k] for k in row.keys()}, **incoming}), review_lock.review_subtasks(conn, int(row["id"])))


def check_fork_parent(conn: sqlite3.Connection, parent: sqlite3.Row, new_state: Optional[str], actor: str, *,
                      decided: Optional[Any], seq: int, now: float) -> None:
    if _exempt(parent, actor, None, decided):
        return
    if new_state == rules.REVIEW:
        _refuse(review_blockers(conn, parent), review_lock.review_subtasks(conn, int(parent["id"])))
    elif new_state is None:
        withdraw_review(conn, parent, seq=seq, now=now, why="the agent forked an open task")


def withdraw_review(conn: sqlite3.Connection, row: Mapping[str, Any], *, seq: int, now: float, why: str) -> bool:
    if row["state"] != rules.REVIEW or row["lane"] == lane.SWARM or row["swarm_ref"]:
        return False
    flow.on_state_write(conn, row, rules.OPEN, CLAUDE, now, None, working=False, decided=lineage.Decided(lineage.CARNIVORE, f"{WITHDRAWN}: {why}"))
    forks.write_state(conn, int(row["id"]), forks.StateChange(rules.OPEN, False, False), seq=seq, now=now, claimant="")
    return True


def after_agent_post(conn: sqlite3.Connection, row: Mapping[str, Any], kind: str, text: str, author_key: str, *, seq: int, now: float) -> bool:
    if row["state"] != rules.REVIEW or author_key in _SYSTEM_KEYS:
        return False
    if kind == QUESTION:
        return withdraw_review(conn, row, seq=seq, now=now, why="the agent asked a question")
    queued = pending_handoffs([text])
    return bool(queued) and withdraw_review(conn, row, seq=seq, now=now, why=f"the handoff {', '.join(queued)} is queued")


__all__ = ["GUARD_NOTE", "HANDOFF_ROOT", "ReplyPlan", "STORED_AS_ANSWER_TO", "WITHDRAWN", "after_agent_post", "check_fork_parent", "check_review", "handoff_result",
           "handoff_script", "pending_handoffs", "plan_reply", "review_blockers", "unanswered_owner_message", "withdraw_review"]
