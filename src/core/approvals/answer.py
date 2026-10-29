
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

from src.core.approvals.extract import (
    KIND_ASK, REVIEW_CONFIRM_LABEL, ROLE_OPTION, ROLE_OTHER, ROLE_SUBMIT, Dialog, extract_dialog, extract_review)
from src.core.approvals.plain_answer import PLAIN_NO, plain_label

UP, DOWN, ENTER, ESC, SPACE = "\x1b[A", "\x1b[B", "\r", "\x1b", " "

SETTLE_SECONDS: float = 0.15
ARROW_GAP_SECONDS: float = 0.05
ESC_GAP_SECONDS: float = 0.15


class AnswerRefused(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Choice:

    option: Optional[str] = None
    options: Optional[List[str]] = None
    other: Optional[str] = None
    dismiss: bool = False
    plain: Optional[str] = None

    @property
    def kind(self) -> str:
        if self.plain is not None:
            return f"plain_{self.plain}"
        return ("dismiss" if self.dismiss else "other" if self.other is not None
                else "options" if self.options is not None else "option")


Capture = Callable[[], Awaitable[Optional[str]]]
Send = Callable[[str], Awaitable[None]]


async def _read(capture: Capture, family: Optional[str], fingerprint: str) -> Dialog:
    dialog = extract_dialog(await capture(), family)
    if dialog is None:
        raise AnswerRefused("no_dialog")
    if dialog.fingerprint != fingerprint:
        raise AnswerRefused("dialog_changed")
    return dialog


async def _move_to(index: int, dialog: Dialog, read: Callable[[], Awaitable[Dialog]],
                   send: Send) -> Dialog:
    if dialog.cursor is None:
        raise AnswerRefused("cursor_unreadable")
    delta = index - dialog.cursor
    for _ in range(abs(delta)):
        await send(DOWN if delta > 0 else UP)
        await asyncio.sleep(ARROW_GAP_SECONDS)
    if delta:
        await asyncio.sleep(SETTLE_SECONDS)
        dialog = await read()
    if dialog.cursor != index:
        raise AnswerRefused("cursor_mismatch")
    return dialog


async def _confirm_review(answered: Dialog, capture: Capture, send: Send) -> None:
    if answered.kind != KIND_ASK:
        return
    await asyncio.sleep(SETTLE_SECONDS)
    review = extract_review(await capture())
    if review is None:
        return
    fp = review.fingerprint

    async def read_review() -> Dialog:
        again = extract_review(await capture())
        if again is None or again.fingerprint != fp:
            raise AnswerRefused("dialog_changed")
        return again

    idx = review.index_of(REVIEW_CONFIRM_LABEL)
    if idx is None:
        raise AnswerRefused("no_such_option")
    await _move_to(idx, review, read_review, send)
    await send(ENTER)


async def answer_dialog(*, family: Optional[str], fingerprint: str, choice: Choice,
                        capture: Capture, send: Send) -> Dialog:
    first = await _read(capture, family, fingerprint)

    async def read() -> Dialog:
        return await _read(capture, family, fingerprint)

    if choice.plain is not None:
        label = plain_label(first, choice.plain)
        if label is None and choice.plain != PLAIN_NO:
            raise AnswerRefused("no_plain_yes")
        choice = Choice(option=label) if label is not None else Choice(dismiss=True)
    if choice.dismiss:
        await send(ESC)
        await asyncio.sleep(ESC_GAP_SECONDS)
        return first
    if choice.other is not None:
        if first.multi_select:
            raise AnswerRefused("other_needs_single_select")
        idx = first.index_of_role(ROLE_OTHER)
        if idx is None:
            raise AnswerRefused("no_other_row")
        await _move_to(idx, first, read, send)
        await send(choice.other)
        await asyncio.sleep(SETTLE_SECONDS)
        await send(ENTER)
        await _confirm_review(first, capture, send)
        return first
    labels = choice.options if choice.options is not None else [choice.option or ""]
    if not first.multi_select:
        if len(labels) != 1:
            raise AnswerRefused("not_multi_select")
        idx = first.index_of(labels[0])
        if idx is None:
            raise AnswerRefused("no_such_option")
        await _move_to(idx, first, read, send)
        await send(ENTER)
        await _confirm_review(first, capture, send)
        return first
    if any(first.index_of(label) is None for label in labels):
        raise AnswerRefused("no_such_option")
    wanted = set(labels)
    dialog = first
    for label in [r.label for r in first.rows if r.role == ROLE_OPTION]:
        i = dialog.index_of(label)
        if i is None or dialog.rows[i].checked == (label in wanted):
            continue
        dialog = await _move_to(i, dialog, read, send)
        await send(SPACE)
        await asyncio.sleep(SETTLE_SECONDS)
        dialog = await read()
        if dialog.rows[i].checked != (label in wanted):
            raise AnswerRefused("toggle_failed")
    submit = dialog.index_of_role(ROLE_SUBMIT)
    if submit is None:
        raise AnswerRefused("no_submit_row")
    await _move_to(submit, dialog, read, send)
    await send(ENTER)
    await _confirm_review(first, capture, send)
    return first
