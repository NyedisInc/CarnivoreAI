
from __future__ import annotations

import sqlite3
from typing import Dict, Mapping, Sequence

from src.cplugs.huddle.cards.columns import CARD_COLS
from src.cplugs.huddle import answers, artifacts, blockers, board, corrections, waits, files, fork, from_project, github_issue, inbox, item_marker, item_owner, kinds, lifecycle, nudges, quotes, review, review_checks, rich_ask, rules, schedule_offer, status_lines, structured, title as titles, triggers

ITEM_COLS = ("id, list_key, text, note, position, created_by, created_key, swarm_ref, state, claude_done, created_at, "
              "updated_at, revision, created_seq, seq, deleted, kind, attention_seq, seen_seq, joe_seq, claude_read_seq, "
              "claude_working, group_id, info_seq, call_seq, review_description, review_summary, review_link, review_where, review_action, review_checks, title, flag_color, flag_reason, github_issue, source_item_id, "
              f"{item_owner.COLUMN}, {item_owner.TAG_COLUMN}, lane, perceived_ask, {blockers.SELECT_COL}, {waits.SELECT_COL}, "
              "COALESCE((SELECT t.cursor FROM work_sends t WHERE t.list_key = work_items.list_key), 0) AS told_seq, "
              f"(SELECT COUNT(*) FROM work_messages m WHERE m.item_id = work_items.id AND {kinds.unread_sql(kinds.INFO)}) AS info_unread, "
              f"(SELECT COUNT(*) FROM work_messages m WHERE m.item_id = work_items.id AND {kinds.unread_sql(kinds.ATTENTION)}) "
              "AS attention_unread, "
              "(SELECT m.parts FROM work_messages m WHERE m.item_id = work_items.id AND m.kind = 'attention' AND m.seen = 0 "
              "AND m.parts LIKE '{\"action\"%' ORDER BY m.id DESC LIMIT 1) AS look_parts, "
              "(SELECT COUNT(*) FROM work_messages m WHERE m.item_id = work_items.id AND m.author = 'claude' AND m.kind = 'answer' AND m.seen = 0 "
              "AND m.parts LIKE '{\"quote\"%') AS answer_unread, "
              f"(SELECT COUNT(*) FROM work_messages m WHERE m.item_id = work_items.id AND {kinds.unread_sql(kinds.INFO)} "
              f"AND m.seq > COALESCE((SELECT MAX(s.seq) FROM work_messages s WHERE s.item_id = work_items.id AND s.author_key = '{status_lines.KEY}'), 0)) AS info_pending, "
              f"{fork.SELECT_COLS}, {from_project.SELECT_COLS}, {inbox.SELECT_COLS}, {triggers.SELECT_COLS}, {CARD_COLS}, {nudges.SELECT_COLS}")
MSG_COLS = f"id, item_id, author, author_key, kind, text, answered, created_at, seq, seen, parts, category"


def number_open(rows: Sequence[sqlite3.Row]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for row in rows:
        if row["state"] not in rules.APPROVED_STATES:
            out[row["id"]] = len(out) + 1
    return out


def numbers_in_view(rows: Sequence[sqlite3.Row], statuses: Mapping[int, str], view: str) -> Dict[int, int]:
    def rank(r: sqlite3.Row) -> int:
        status = statuses.get(r["id"], lifecycle.OPEN)
        if view == lifecycle.VIEW_STATUS and lifecycle.row_action(r, status):
            return -1
        return lifecycle.section_rank(status)

    if view == lifecycle.VIEW_STATUS:
        rows = sorted(rows, key=lambda r: (rank(r), r["position"], r["id"]))
    else:
        first: Dict[object, int] = {}
        for at, r in enumerate(rows):
            first.setdefault(r["group_id"], at)
        rows = sorted(rows, key=lambda r: (first[r["group_id"]], rank(r), r["position"], r["id"]))
    return number_open(rows)


def item_dict(row: sqlite3.Row, asking: bool = False) -> dict:
    item_status = lifecycle.status(row, asking)
    needs = lifecycle.row_action(row, item_status)
    return {
        "id": row["id"], "list": row["list_key"], "text": row["text"], "note": row["note"],
        "position": row["position"], "created_by": row["created_by"], "created_key": row["created_key"],
        "swarm_ref": row["swarm_ref"], "source_item_id": row["source_item_id"], "state": row["state"], "kind": row["kind"],
        "created_at": row["created_at"], "updated_at": row["updated_at"], "revision": row["revision"],
        "created_seq": row["created_seq"], "seq": row["seq"], "deleted": bool(row["deleted"]),
        "unread": row["attention_seq"] > row["seen_seq"], "status": item_status,
        "note_waiting": lifecycle.note_waiting(row, item_status),
        "lane": row["lane"], "perceived_ask": row["perceived_ask"], "group": row["group_id"], **kinds.lights(row), **review.wire(row), **review_checks.wire(row), titles.FIELD: row[titles.FIELD], **item_marker.wire(row), **github_issue.wire(row),
        triggers.FIELD: triggers.wire(row), **fork.wire(row), **from_project.wire(row), **inbox.wire(row),
        "section": lifecycle.section_of(item_status),
        "needs_you": needs is not None,
        "needs_action": needs,
        **nudges.wire(row),
        **item_owner.wire(row),
        **blockers.wire(row),
        **waits.wire(row),
    }


def message_dict(row: sqlite3.Row) -> dict:
    context, questions = structured.wire(row)
    out = {
        "id": row["id"], "item_id": row["item_id"], "author": row["author"], "author_key": row["author_key"], "kind": row["kind"],
        "text": row["text"], "answered": bool(row["answered"]), "created_at": row["created_at"],
        "seq": row["seq"], "unread": row["kind"] in kinds.READ_ONE_KINDS and not row["seen"],
        **({"quiet": True} if row["kind"] == kinds.COMMENT else {}),
        "context": context, "questions": questions,
    }
    if row["answered"] == rules.ANSWERED_SUPERSEDED:
        out["superseded"] = True
    raw = row["parts"] if "parts" in row.keys() else ""
    form = rich_ask.form_of(raw)
    if form is not None:
        out["form"] = form
    given = answers.wire(raw)
    if given is not None:
        out.update(given)
    attached = files.wire(raw)
    page = artifacts.wire(raw)
    if page is not None:
        out["artifact"] = page
        attached = [f for f in attached or [] if f["id"] != page["id"]] or None
    if attached is not None:
        out["files"] = attached
    card = board.wire(raw)
    if card is not None:
        out[board.KEY] = card
    sent = board.round_wire(raw)
    if sent is not None:
        out[board.ROUND_KEY] = sent
    if "category" in row.keys() and row["category"]:
        out["category"] = row["category"]
    offered = schedule_offer.read(raw)
    if offered is not None:
        out[schedule_offer.KEY] = offered
    quoted = quotes.wire(raw)
    if quoted is not None:
        out["quote"] = quoted
    withdrawn = corrections.wire(raw)
    if withdrawn is not None:
        out[corrections.KEY] = withdrawn
    return out
