
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import structlog

from src.core.approvals.answer import DOWN, ENTER, UP, AnswerRefused
from src.core.approvals.ask_questions import AskQuestion, AskQuestions, matching_question, option_rows, prefix
from src.core.approvals.extract import (
    KIND_ASK, REVIEW_CONFIRM_LABEL, ROLE_SUBMIT, Dialog, extract_dialog, extract_review, squash)
from src.core.approvals.review_read import NOTES_EMPTY_ENTRY, NOTES_IDLE, notes_line, review_answers

from src.models.dialogs import is_plain_line

logger = structlog.get_logger()

LEFT, RIGHT, NOTES_KEY = "\x1b[D", "\x1b[C", "n"
FIRST_ROW: int = 0

POLL_SECONDS: float = 0.05
KEY_TIMEOUT_SECONDS: float = 3.0
STRIKES: int = 2
_REVIEW_COMPARE_CHARS: int = 80
_OTHER_PRISTINE = "typesomething"

_QUESTION, _REVIEW, _GONE, _FOREIGN, _UNMATCHED = "question", "review", "gone", "foreign", "unmatched"


@dataclass(frozen=True)
class QuestionAnswer:

    option: Optional[str] = None
    options: Optional[Tuple[str, ...]] = None
    other: Optional[str] = None
    notes: Optional[str] = None

    @property
    def skipped(self) -> bool:
        return self.option is None and self.options is None and self.other is None and self.notes is None


@dataclass(frozen=True)
class Screen:

    kind: str
    text: str
    dialog: Optional[Dialog] = None
    qidx: Optional[int] = None
    problem: Optional[str] = None

    @property
    def cursor(self) -> Optional[int]:
        return self.dialog.cursor if self.dialog is not None else None

    @property
    def body(self) -> tuple:
        if self.dialog is None:
            return (self.kind, self.qidx)
        pairs = review_answers(self.text) if self.kind == _REVIEW else None
        return (self.kind, self.qidx, tuple((r.label, r.checked) for r in self.dialog.rows),
                tuple(pairs[0]) if pairs else (), notes_line(self.text) if self.kind == _QUESTION else None)

    @property
    def sig(self) -> tuple:
        return (*self.body, self.cursor)


def _clean(text: str, name: str) -> str:
    if not text.strip():
        raise AnswerRefused("empty_other" if name == "other" else "empty_notes")
    if not is_plain_line(text):
        raise AnswerRefused(f"{name}_not_plain_text")
    return text


def validate(asked: AskQuestions, answers: List[QuestionAnswer]) -> None:
    questions = asked.questions
    if len(answers) != len(questions):
        raise AnswerRefused("answer_count_mismatch")
    if len({squash(q.question) for q in questions}) != len(questions):
        raise AnswerRefused("ambiguous_questions")
    if all(a.skipped for a in answers):
        raise AnswerRefused("empty_answer")
    for q, a in zip(questions, answers):
        if a.skipped:
            continue
        labels = {squash(o.label) for o in q.options}
        if q.multi_select and q.has_preview:
            raise AnswerRefused("unsupported_question")
        if q.multi_select:
            if a.option is not None:
                raise AnswerRefused("not_single_select")
            wanted = list(a.options or ())
            if len({squash(w) for w in wanted}) != len(wanted):
                raise AnswerRefused("no_such_option")
        else:
            if a.options is not None:
                raise AnswerRefused("not_multi_select")
            wanted = [a.option] if a.option is not None else []
            if (a.option is None) == (a.other is None):
                raise AnswerRefused("empty_answer")
        if not wanted and a.other is None:
            raise AnswerRefused("empty_answer")
        if any(squash(w) not in labels for w in wanted):
            raise AnswerRefused("no_such_option")
        if a.other is not None:
            if q.has_preview:
                raise AnswerRefused("no_other_row")
            _clean(a.other, "other")
        if a.notes is not None:
            if q.multi_select or not q.has_preview:
                raise AnswerRefused("notes_not_supported")
            _clean(a.notes, "notes")


def expected_answer(q: AskQuestion, a: QuestionAnswer) -> str:
    if not q.multi_select:
        label = next((o.label for o in q.options if squash(o.label) == squash(a.option or "")), None)
        return a.other if a.other is not None else label or ""
    picked = [o.label for o in q.options if squash(o.label) in {squash(w) for w in (a.options or ())}]
    return ", ".join([*picked, *([a.other] if a.other is not None else [])])


_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unquote(shown: str) -> str:
    def decode(m: "re.Match[str]") -> str:
        try:
            return json.loads(m.group(0))
        except ValueError:
            return m.group(0)
    return _QUOTED.sub(decode, shown)


def _review_matches(shown: str, want: str, multi: bool) -> bool:
    unquoted = _unquote(shown)
    return _review_equal(shown, want, multi) or (unquoted != shown and _review_equal(unquoted, want, multi))


def _review_equal(shown: str, want: str, multi: bool) -> bool:
    s, w = squash(shown), squash(want)
    if s == w or (len(w) > _REVIEW_COMPARE_CHARS and s[:_REVIEW_COMPARE_CHARS] == w[:_REVIEW_COMPARE_CHARS]):
        return True
    if not multi:
        return False
    items = [squash(i) for i in want.split(", ") if i.strip()]
    return len(s.replace(",", "")) == len("".join(items).replace(",", "")) and all(i in s for i in items)


class _Run:

    def __init__(self, asked: AskQuestions, answers: List[QuestionAnswer], capture, send) -> None:
        self.asked, self.answers, self.capture, self.send = asked, answers, capture, send
        self.n = len(asked.questions)
        self.screen: Screen = Screen(_GONE, "")

    async def observe(self) -> Screen:
        text = await self.capture()
        if text is None:
            raise AnswerRefused("no_dialog")
        dialog = extract_dialog(text, "claude")
        if dialog is None:
            review = extract_review(text)
            if review is not None:
                return Screen(_REVIEW, text, review)
            return Screen(_GONE, text, problem="dialog_closed_early")
        if dialog.kind != KIND_ASK or dialog.startup_kind is not None:
            return Screen(_FOREIGN, text, dialog, problem="dialog_changed")
        at = matching_question(dialog, self.asked)
        if at is None:
            return Screen(_UNMATCHED, text, dialog, problem="question_text_mismatch")
        if self.n > 1 and len(dialog.tabs) != self.n or len(dialog.tabs) > 1 and self.n == 1:
            return Screen(_UNMATCHED, text, dialog, at, "question_count_mismatch")
        return Screen(_QUESTION, text, dialog, at)

    async def _settle(self, before: Screen, expect: Callable[[Screen], bool], timeout_reason: str) -> Screen:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + KEY_TIMEOUT_SECONDS
        strikes = 0
        while True:
            await asyncio.sleep(POLL_SECONDS)
            cur = await self.observe()
            if expect(cur):
                return cur
            if cur.problem is None and cur.sig == before.sig:
                strikes = 0
            else:
                strikes += 1
                if strikes >= STRIKES:
                    raise AnswerRefused(cur.problem or "dialog_changed")
            if loop.time() > deadline:
                raise AnswerRefused(timeout_reason)

    async def press(self, key: str, expect: Callable[[Screen], bool], reason: str = "key_not_applied") -> Screen:
        before = self.screen
        await self.send(key)
        self.screen = await self._settle(before, expect, reason)
        return self.screen

    def _same_but_cursor(self, row: int) -> Callable[[Screen], bool]:
        was = self.screen.body
        return lambda s: s.body == was and s.cursor == row

    async def move_cursor(self, row: int) -> None:
        while True:
            at = self.screen.cursor
            if at is None:
                raise AnswerRefused("cursor_unreadable")
            if at == row:
                return
            step = 1 if row > at else -1
            await self.press(DOWN if step > 0 else UP, self._same_but_cursor(at + step))

    def _rows(self, q: AskQuestion) -> Tuple[List[int], Optional[int]]:
        found = option_rows(self.screen.dialog, q) if self.screen.dialog is not None else None
        if found is None:
            raise AnswerRefused("option_text_mismatch")
        return found

    async def rewind(self) -> None:
        while True:
            s = self.screen
            if s.kind == _REVIEW:
                await self.press(LEFT, lambda x: x.kind == _QUESTION and x.qidx == self.n - 1)
            elif s.kind == _QUESTION and s.qidx == 0:
                return
            elif s.kind == _QUESTION:
                await self.move_cursor(FIRST_ROW)
                at = s.qidx
                await self.press(LEFT, lambda x, at=at: x.kind == _QUESTION and x.qidx == at - 1)
            else:
                raise AnswerRefused(s.problem or "dialog_changed")

    def _direct(self) -> bool:
        return self.n == 1 and not self.asked.questions[0].multi_select

    def _after(self, k: int) -> Callable[[Screen], bool]:
        if k + 1 < self.n:
            return lambda s: s.kind == _QUESTION and s.qidx == k + 1
        return lambda s: s.kind == _REVIEW

    async def type_other(self, q: AskQuestion, row: int, text: str, multi: bool) -> None:
        shown = self.screen.dialog.rows[row]
        if not squash(shown.label).lower().startswith(_OTHER_PRISTINE) or shown.checked:
            raise AnswerRefused("other_row_not_empty")
        head = squash(text)[:24]
        count = len(self.screen.dialog.rows)
        ticks = tuple(r.checked for i, r in enumerate(self.screen.dialog.rows) if i != row)
        before = self.screen
        await self.send(text)
        self.screen = await self._settle(before, lambda s: (
            s.kind == _QUESTION and s.qidx == before.qidx and s.cursor == row and prefix(s.dialog.rows[row].label) == head
            and (not multi or s.dialog.rows[row].checked is True)
            and tuple(r.checked for i, r in enumerate(s.dialog.rows) if i != row) == ticks and len(s.dialog.rows) == count),
            "key_not_applied")

    async def answer_question(self, k: int) -> None:
        q, a = self.asked.questions[k], self.answers[k]
        if self.screen.kind != _QUESTION or self.screen.qidx != k:
            raise AnswerRefused(self.screen.problem or "dialog_changed")
        await self.move_cursor(FIRST_ROW)
        if a.skipped:
            await self.press(RIGHT, self._after(k))
            return
        rows, other = self._rows(q)
        if not q.multi_select:
            if a.other is not None:
                if other is None:
                    raise AnswerRefused("no_other_row")
                await self.move_cursor(other)
                await self.type_other(q, other, a.other, False)
            else:
                at = next(i for i, o in enumerate(q.options) if squash(o.label) == squash(a.option or ""))
                await self.move_cursor(rows[at])
                if a.notes is not None:
                    if rows[at] == FIRST_ROW and rows[at] + 1 < len(self.screen.dialog.rows):
                        await self.move_cursor(rows[at] + 1)
                        await self.move_cursor(rows[at])
                    await self.add_notes(k, a.notes)
                elif (line := notes_line(self.screen.text)) is not None and line.strip() != NOTES_IDLE:
                    raise AnswerRefused("notes_not_empty")
            if self._direct():
                await self.submit()
            else:
                await self.press(ENTER, self._after(k), "key_not_applied")
            return
        wanted = {squash(w) for w in (a.options or ())}
        for j, option in enumerate(q.options):
            row = rows[j]
            want = squash(option.label) in wanted
            if self.screen.dialog.rows[row].checked is want:
                continue
            await self.move_cursor(row)
            was = self.screen
            await self.press(" ", lambda s, row=row, want=want, was=was: (
                s.kind == _QUESTION and s.qidx == k and s.cursor == row and s.dialog.rows[row].checked is want
                and [r.checked for i, r in enumerate(s.dialog.rows) if i != row]
                == [r.checked for i, r in enumerate(was.dialog.rows) if i != row]), "toggle_failed")
        if a.other is not None:
            if other is None:
                raise AnswerRefused("no_other_row")
            await self.move_cursor(other)
            await self.type_other(q, other, a.other, True)
        elif other is not None and self.screen.dialog.rows[other].checked:
            raise AnswerRefused("other_row_not_empty")
        submit = self.screen.dialog.index_of_role(ROLE_SUBMIT)
        if submit is None:
            raise AnswerRefused("no_submit_row")
        await self.move_cursor(submit)
        await self.press(ENTER, self._after(k))

    async def add_notes(self, k: int, notes: str) -> None:
        line = notes_line(self.screen.text)
        if line is None or line.strip() != NOTES_IDLE:
            raise AnswerRefused("notes_not_empty")
        row = self.screen.cursor
        await self.press(NOTES_KEY, lambda s: s.kind == _QUESTION and s.qidx == k and s.cursor == row
                         and (notes_line(s.text) or "").startswith(NOTES_EMPTY_ENTRY), "notes_not_opened")
        head = squash(notes)[:24]
        before = self.screen
        await self.send(notes)
        self.screen = await self._settle(before, lambda s: (
            s.kind == _QUESTION and s.qidx == k and s.cursor == row and squash(notes_line(s.text) or "")[:24] == head),
            "notes_not_applied")

    async def review_and_submit(self) -> None:
        shown = review_answers(self.screen.text)
        if shown is None:
            raise AnswerRefused("dialog_changed")
        pairs, warned = shown
        have = {squash(q): a for q, a in pairs}
        left_out = sum(a.skipped for a in self.answers)
        if warned != (left_out > 0) or len(pairs) != self.n - left_out or len(have) != len(pairs):
            raise AnswerRefused("review_mismatch")
        for q, a in zip(self.asked.questions, self.answers):
            if a.skipped:
                if squash(q.question) in have:
                    raise AnswerRefused("review_mismatch")
            elif not _review_matches(have.get(squash(q.question), ""), expected_answer(q, a), q.multi_select):
                raise AnswerRefused("review_mismatch")
        idx = self.screen.dialog.index_of(REVIEW_CONFIRM_LABEL)
        if idx is None:
            raise AnswerRefused("no_such_option")
        await self.move_cursor(idx)
        await self.submit()

    async def submit(self) -> None:
        await self.send(ENTER)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + KEY_TIMEOUT_SECONDS
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                cur = await self.observe()
            except AnswerRefused:
                cur = None
            if cur is not None and (cur.kind in (_GONE, _FOREIGN) or (cur.kind == _UNMATCHED and cur.qidx is None)):
                self.screen = cur
                return
            if loop.time() > deadline:
                raise AnswerRefused("submit_not_confirmed")

    async def run(self) -> str:
        self.screen = await self.observe()
        if self.screen.kind == _GONE:
            raise AnswerRefused("no_dialog")
        await self.rewind()
        for k in range(self.n):
            await self.answer_question(k)
        if self._direct():
            return "direct"
        await self.review_and_submit()
        return "review"


async def answer_all(*, asked: AskQuestions, answers: List[QuestionAnswer], capture, send) -> str:
    validate(asked, answers)
    return await _Run(asked, answers, capture, send).run()
