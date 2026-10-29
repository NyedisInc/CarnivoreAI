
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Mapping, Optional, Sequence

import structlog

from src.cplugs.huddle import actor_log, inbox, lineage, rules, structured
from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.roles import wait_stuck

logger = structlog.get_logger()

STALL = "stall"
SESSION_GONE, WAKE_FAILED = "session_gone", "wake_failed"
TAG_CATEGORIES = (SESSION_GONE, WAKE_FAILED)
OWNER_GONE, OWNER_WAKE_FAILED = "owner_gone", "owner_wake_failed"
OWNER_CATEGORIES = (OWNER_GONE, OWNER_WAKE_FAILED)
INBOX_STUCK = inbox.STUCK_CATEGORY
WAIT_STUCK = "wait_stuck"
LEAD_GONE = "lead_gone"
CARNIVORE_CATEGORIES = (STALL, *TAG_CATEGORIES, *OWNER_CATEGORIES, INBOX_STUCK, WAIT_STUCK, LEAD_GONE)
FILE_MYSELF, START_SESSION, WAIT = "file", "session", "wait"
INBOX_OPTIONS = (FILE_MYSELF, START_SESSION, WAIT)
INBOX_LABELS = {FILE_MYSELF: "file it myself", START_SESSION: "start a session", WAIT: "wait"}
UNSTICK, PARK, CANCEL = "unstick", "park", "cancel"
PUSH, DROP = wait_stuck.PUSH, wait_stuck.DROP
WAIT_OPTIONS, WAIT_LABELS = wait_stuck.OPTIONS, wait_stuck.LABELS
STALL_OPTIONS = (UNSTICK, PARK, CANCEL)
QUESTION_ID = "q1"
STALL_PROMPT = "this task looks stuck. what now?"
PROMPTS = {STALL: STALL_PROMPT, SESSION_GONE: "the agent this task is tagged to is gone. what now?",
           WAKE_FAILED: "the agent this task is tagged to would not wake. what now?",
           OWNER_GONE: "the session working on this task is gone. what now?",
           OWNER_WAKE_FAILED: "the session working on this task would not wake. what now?",
           INBOX_STUCK: "nobody filed what you typed. what now?",
           WAIT_STUCK: "this task is stuck waiting past two deadlines. what now?",
           LEAD_GONE: "this project's lead is gone. who leads it now?"}
PARK_DETAIL = "stall_park"


def carnivore_ask(store: Any, item_id: int, *, category: str, context: str, options: Sequence[str],
                  labels: Optional[Mapping[str, str]] = None, prompt: Optional[str] = None,
                  extra_questions: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    question = {"id": QUESTION_ID, "type": "single", "prompt": prompt or PROMPTS[category], "required": True,
                "options": [{"id": option, "label": (labels or {}).get(option, option)} for option in options]}
    text, parts = structured.build(None, context, [question, *extra_questions])
    posted = store.post(item_id, text, actor=rules.CLAUDE, kind=rules.QUESTION, author_key=rules.CARNIVORE_KEY, parts=parts, category=category)
    logger.info("task_manager_carnivore_asked", item=item_id, category=category)
    return posted


def has_open(conn: sqlite3.Connection, item_id: int, category: str) -> bool:
    return conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND kind = 'question' AND answered = 0 AND category = ? LIMIT 1",
                        (item_id, category)).fetchone() is not None


def apply(conn: sqlite3.Connection, item: Mapping[str, Any], category: str, choice: str, now: float,
          answers: Optional[Mapping[str, Any]] = None) -> str:
    if category not in CARNIVORE_CATEGORIES:
        return ""
    if category in TAG_CATEGORIES and item["tagged_session_key"]:
        conn.execute("UPDATE work_items SET tagged_session_key = '', revision = revision + 1 WHERE id = ?", (item["id"],))
    if category in OWNER_CATEGORIES and item["owner_session_key"]:
        conn.execute("UPDATE work_items SET owner_session_key = '', claude_working = 0, claude_working_by = '', revision = revision + 1 WHERE id = ?",
                     (item["id"],))
    if category == WAIT_STUCK:
        return wait_stuck.apply_choice(conn, item, choice, answers, now)
    if choice == PARK and item["state"] == rules.OPEN:
        flow.on_state_write(conn, item, rules.TODO, rules.JOE, now, None, working=False,
                            decided=lineage.Decided(actor_log.by_for(rules.JOE), PARK_DETAIL))
        conn.execute("UPDATE work_items SET state = ?, claude_working = 0, claude_working_by = '', revision = revision + 1 WHERE id = ?",
                     (rules.TODO, item["id"]))
    return choice
