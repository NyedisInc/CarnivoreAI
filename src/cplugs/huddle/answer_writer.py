
from __future__ import annotations

import json
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, Optional

import structlog

from src.cplugs.huddle import answers as answer_wire, kinds, moves, rich_ask, rules, structured, triggers, waits
from src.cplugs.huddle.roles import ask as carnivore_ask
from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.rules import JOE, TaskManagerAnswered, TaskManagerInvalid, TaskManagerNotFound
from src.cplugs.huddle.wire import MSG_COLS, message_dict

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()


class AnswerWriter:

    def __init__(self, store: "TaskManagerStore") -> None:
        self._store = store

    @staticmethod
    def _question(conn: Any, message_id: Any) -> Any:
        row = conn.execute(
            f"SELECT {MSG_COLS} FROM work_messages WHERE id = ? AND kind = 'question' "
            "AND item_id IN (SELECT id FROM work_items WHERE deleted = 0)", (message_id,)).fetchone() if isinstance(message_id, int) else None
        if row is None:
            raise TaskManagerNotFound(f"no huddle question {message_id}")
        return row

    @staticmethod
    def _answer_id(conn: Any, row: Any) -> Optional[int]:
        found = conn.execute("SELECT id FROM work_messages WHERE item_id = ? AND author = 'joe' AND parts LIKE ? ORDER BY id DESC LIMIT 1",
                             (row["item_id"], f'{{"v": 2, "answers_to": {int(row["id"])},%')).fetchone()
        return int(found[0]) if found else None

    def read(self, message_id: int) -> Dict[str, Any]:
        with closing(self._store._read_connection()) as conn:
            row = self._question(conn, message_id)
            answer_id = self._answer_id(conn, row)
        context, _strings = structured.wire(row)
        return {"item": row["item_id"], "message": message_id, "typed": rich_ask.is_typed(row["parts"]),
                "ask": {"context": context, "questions": structured.form_of_row(row)},
                "answered": bool(row["answered"]), "answer_message_id": answer_id}

    def _replay(self, conn: Any, row: Any, answers: Any) -> Dict[str, Any]:
        standing = self._answer_id(conn, row)
        stored = conn.execute("SELECT parts FROM work_messages WHERE id = ?", (standing,)).fetchone() if standing else None
        try:
            checked = answer_wire.validate(structured.form_of_row(row), answers)
            same = stored is not None and json.loads(stored["parts"]) == json.loads(answer_wire.dump(row["id"], checked))
        except (TaskManagerInvalid, ValueError, TypeError):
            same = False
        if not same:
            raise TaskManagerAnswered(f"question {row['id']} is already answered")
        message = message_dict(conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE id = ?", (standing,)).fetchone())
        return {"item": self._store.item(row["item_id"]), "message": message, "replayed": True}

    def submit(self, message_id: int, answers: Any, ack_through: Optional[int] = None) -> Dict[str, Any]:
        store = self._store
        with closing(store._connect(True)) as conn, conn:
            row = self._question(conn, message_id)
            if row["answered"]:
                return self._replay(conn, row, answers)
            questions = structured.form_of_row(row)
            checked = answer_wire.validate(questions, answers)
            text = rules.clean_text(answer_wire.text_of(questions, checked), "text", rules.MAX_MESSAGE)
            item = store._row(conn, row["item_id"])
            seq = store._next_seq(conn)
            kinds.acknowledge(conn, item["id"], None if moves.is_swarm_lane(item) else ack_through)
            triggers.resume_skipped(conn, item["id"], store._clock(), (triggers.SKIP_JOE,))
            conn.execute("UPDATE work_messages SET answered = 1, seq = ? WHERE id = ?", (seq, message_id))
            cur = conn.execute(
                "INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts, seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (item["id"], JOE, rules.REPLY, text, store._clock(), seq, rules.OWNER_KEY, answer_wire.dump(message_id, checked)))
            conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item["id"]))
            if (item["state"] == rules.REVIEW or (item["state"] == rules.WAITING and waits.on_owner(conn, item["id"]))) and row["category"] != carnivore_ask.WAIT_STUCK:
                flow.on_state_write(conn, item, rules.OPEN, JOE, store._clock(), None, working=False)
                conn.execute("UPDATE work_items SET state = ?, claude_done = 0, claude_working = 0, claude_working_by = '', "
                             "revision = revision + 1 WHERE id = ?", (rules.OPEN, item["id"]))
            carnivore = None
            if row["category"] in carnivore_ask.CARNIVORE_CATEGORIES:
                carnivore = {"category": row["category"], "choice": carnivore_ask.apply(
                    conn, item, row["category"], checked.get(carnivore_ask.QUESTION_ID, {}).get("choice", ""), store._clock())}
            store._mark(conn, item["id"], JOE, seq)
            message = message_dict(conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE id = ?", (cur.lastrowid,)).fetchone())
        store._commit_notify(item["list_key"])
        store._acted_on(item["id"])
        logger.info("task_manager_form_answered", item=item["id"], question=message_id, answers=len(checked))
        return {"item": store.item(item["id"]), "message": message, **({"carnivore": carnivore} if carnivore else {})}
