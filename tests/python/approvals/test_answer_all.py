
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.approvals import answer_all as driver
from src.core.approvals.answer import AnswerRefused
from src.core.approvals.answer_all import QuestionAnswer, answer_all
from src.core.approvals.ask_questions import AskQuestions, parse_questions_input, questions_in_lines, serve_fields
from src.core.approvals.extract import extract_dialog
from tests.python.approvals.ask_pane_sim import DOWN, ENTER, ESC, LEFT, UP, AskPane

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "approvals" / "multiq"


def fixture_text(name: str) -> str:
    return (FIX / f"{name}.txt").read_text()


def asked_from(name: str) -> AskQuestions:
    return AskQuestions("toolu_1", parse_questions_input(json.loads((FIX / f"{name}.json").read_text())))


@pytest.fixture(autouse=True)
def fast_keys(monkeypatch) -> None:
    monkeypatch.setattr(driver, "POLL_SECONDS", 0.001)
    monkeypatch.setattr(driver, "KEY_TIMEOUT_SECONDS", 0.2)


THREE = asked_from("ask-3q")
ANSWERS = [QuestionAnswer(option="Green"), QuestionAnswer(options=("Cheese", "Peppers"), other="Corn"),
           QuestionAnswer(option="Large")]


def pane_for(asked: AskQuestions, tab: int = 0, **kw: Any) -> AskPane:
    return AskPane([{"question": q.question, "header": q.header, "multiSelect": q.multi_select,
                     "options": [{"label": o.label, "description": o.description, **({"preview": o.preview} if o.preview else {})}
                                 for o in q.options]} for q in asked.questions], tab, **kw)


def run(pane: AskPane, asked: AskQuestions = THREE, answers: List[QuestionAnswer] = ANSWERS) -> str:
    return asyncio.run(answer_all(asked=asked, answers=answers, capture=pane.capture, send=pane.send))


def refused(pane: AskPane, asked: AskQuestions = THREE, answers: List[QuestionAnswer] = ANSWERS) -> str:
    with pytest.raises(AnswerRefused) as exc:
        run(pane, asked, answers)
    return exc.value.reason



def test_every_question_is_answered_in_order_and_submitted_once():
    pane = pane_for(THREE, tab=1)
    assert run(pane) == "review"
    assert pane.submitted == {0: ("opt", 1), 1: {"ticks": {0, 2}, "other_on": True}, 2: ("opt", 1)}
    assert pane.typed == {1: "Corn"}
    assert pane.keys.count(ESC) == 0 and pane.stray == []
    assert pane.keys.count(LEFT) == 1 and pane.keys[-1] == ENTER and pane.keys.count("Corn") == 1
    assert pane.keys.count(ENTER) == 4
    assert not pane.rejected


def test_an_empty_answer_leaves_its_question_unanswered_and_the_rest_is_submitted():
    pane = pane_for(THREE)
    assert run(pane, THREE, [ANSWERS[0], QuestionAnswer(), ANSWERS[2]]) == "review"
    assert pane.submitted == {0: ("opt", 1), 2: ("opt", 1)} and pane.typed == {}
    assert pane.keys.count("\x1b[C") == 1 and pane.stray == [] and not pane.rejected


def test_a_lone_single_select_submits_at_once_and_a_lone_multi_select_goes_through_review():
    one = AskQuestions("t", parse_questions_input({"questions": [{"question": "Pick a fruit?", "header": "Fruit", "multiSelect": False,
                                                                  "options": [{"label": "Apple"}, {"label": "Banana"}]}]}))
    pane = pane_for(one)
    assert run(pane, one, [QuestionAnswer(other="Plum")]) == "direct"
    assert pane.submitted == {0: ("other", "Plum")} and pane.keys == [DOWN, DOWN, "Plum", ENTER]
    multi = AskQuestions("t", parse_questions_input({"questions": [{"question": "Which envs?", "header": "Envs", "multiSelect": True,
                                                                    "options": [{"label": "Staging"}, {"label": "Canary"}]}]}))
    pane = pane_for(multi)
    assert run(pane, multi, [QuestionAnswer(options=("Canary",))]) == "review"
    assert pane.submitted == {0: {"ticks": {1}, "other_on": False}}


def test_a_preview_question_takes_notes_with_n_and_one_enter():
    preview = asked_from("ask-preview")
    pane = pane_for(preview)
    run(pane, preview, [QuestionAnswer(option="List", notes="dense only"), QuestionAnswer(option="Safe")])
    assert pane.notes == {0: "dense only"} and pane.submitted[0] == ("opt", 1)
    assert pane.keys[:4] == [DOWN, "n", "dense only", ENTER] and pane.stray == []


def test_a_retry_over_ticked_boxes_unticks_what_is_not_wanted():
    pane = pane_for(THREE, tab=1)
    pane.sel[1] = {"ticks": {1}, "other_on": False}
    run(pane)
    assert pane.submitted[1]["ticks"] == {0, 2}



def drift_after(pane: AskPane, presses: int, change) -> None:
    def hook(p: AskPane) -> None:
        if len(p.keys) == presses:
            change(p)
    pane.after_key = hook


@pytest.mark.parametrize("at,change,reason", [
    (2, lambda p: p.q[1].update(question="Which sauces?"), "question_text_mismatch"),
    (2, lambda p: p.q[1]["options"][0].update(label="Brie"), "question_text_mismatch"),
    (2, lambda p: setattr(p, "closed", True), "dialog_closed_early"),
    (1, lambda p: setattr(p, "override", "Do you want to proceed?\n  1. Yes\n  2. No\nEsc to cancel"), "dialog_changed"),
    (1, lambda p: setattr(p, "cursor", p.cursor + 1), "dialog_changed"),
], ids=["question_text", "option_text", "closed", "replaced", "another_client_key"])
def test_drift_stops_with_a_named_reason_and_presses_nothing_more(at, change, reason):
    pane = pane_for(THREE)
    drift_after(pane, at, change)
    assert refused(pane) == reason
    assert pane.submitted is None and len(pane.keys) == at


def test_another_client_ticking_a_box_during_an_arrow_press_stops_the_run():
    pane = pane_for(THREE)
    seen: List[int] = []

    def hook(p: AskPane) -> None:
        if p.tab == 1 and p.keys[-1] == DOWN and not seen:
            seen.append(len(p.keys))
            p.sel.setdefault(1, {"ticks": set(), "other_on": False})["ticks"].add(0)
    pane.after_key = hook
    answers = [ANSWERS[0], QuestionAnswer(options=("Peppers",)), ANSWERS[2]]
    assert refused(pane, answers=answers) == "dialog_changed"
    assert pane.submitted is None and len(pane.keys) == seen[0]


def test_free_text_refuses_line_breaks_of_every_kind():
    from src.models.dialogs import is_plain_line
    assert is_plain_line("a b") and not any(is_plain_line(f"a{c}b") for c in "\x85\u2028\u2029\x9b\n\x1b")


def test_a_pane_with_another_question_count_is_refused_before_any_key():
    pane = pane_for(THREE, tabs_shown=4)
    assert refused(pane) == "question_count_mismatch" and pane.keys == []


def test_no_dialog_is_refused_before_any_key():
    pane = pane_for(THREE)
    pane.closed = True
    assert refused(pane) == "no_dialog" and pane.keys == []


def test_the_checks_are_what_stop_the_run(monkeypatch):
    pane = pane_for(THREE)
    drift_after(pane, 2, lambda p: p.q[1].update(question="Which sauces?"))
    monkeypatch.setattr(driver, "matching_question", lambda dialog, asked: dialog.question_index - 1 if dialog.question_index else 0)
    monkeypatch.setattr(driver, "option_rows", lambda dialog, q: (list(range(len(q.options))), None))
    try:
        run(pane)
    except AnswerRefused as exc:
        assert exc.reason not in ("question_text_mismatch", "option_text_mismatch")
    assert len(pane.keys) > 3



@pytest.mark.parametrize("answers,reason", [
    ([QuestionAnswer(option="Green")], "answer_count_mismatch"),
    ([QuestionAnswer(option="Purple"), *ANSWERS[1:]], "no_such_option"),
    ([QuestionAnswer(options=("Red",)), *ANSWERS[1:]], "not_multi_select"),
    ([ANSWERS[0], QuestionAnswer(option="Cheese"), ANSWERS[2]], "not_single_select"),
    ([QuestionAnswer(notes="x"), *ANSWERS[1:]], "empty_answer"),
    ([QuestionAnswer(), QuestionAnswer(), QuestionAnswer()], "empty_answer"),
    ([QuestionAnswer(other="   "), *ANSWERS[1:]], "empty_other"),
    ([QuestionAnswer(other="a\nb"), *ANSWERS[1:]], "other_not_plain_text"),
    ([QuestionAnswer(option="Green", notes="x"), *ANSWERS[1:]], "notes_not_supported"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_a_bad_answer_set_presses_nothing(answers, reason):
    pane = pane_for(THREE)
    assert refused(pane, THREE, answers) == reason and pane.keys == []


def test_enter_is_never_pressed_on_an_empty_other_row():
    pane = pane_for(THREE)
    assert refused(pane, THREE, [QuestionAnswer(other=""), *ANSWERS[1:]]) == "empty_other"
    assert pane.keys == [] and not pane.rejected


def test_a_dirty_other_row_is_refused_not_typed_over():
    pane = pane_for(THREE, tab=1)
    pane.typed[1] = "Old"
    pane.sel[1] = {"ticks": set(), "other_on": True}
    assert refused(pane) == "other_row_not_empty"



@pytest.mark.parametrize("name,ask,kind,qidx,cursor", [
    ("10-multi3-q1of3", "ask-3q", "question", 0, 0),
    ("11-multi3-q2of3-via-right", "ask-3q", "question", 1, 0),
    ("12-multi3-q3of3-via-tab", "ask-3q", "question", 2, 0),
    ("15-multi3-q1-revisit-answered", "ask-3q", "question", 0, 0),
    ("21-multi-cursor-on-next", "ask-3q", "question", 1, 4),
    ("26-review-all-answered", "ask-3q", "review", None, 0),
    ("30-preview-q1of2", "ask-preview", "question", 0, 0),
    ("35-preview-revisit-answered-with-notes", "ask-preview", "question", 0, 0),
    ("51-three-q-60col", "ask-3q-wide", "question", 0, 0),
    ("58-review-q2-unanswered-other-answer", "ask-3q-wide", "review", None, 0),
    ("05-single-after-enter-t3", "ask-3q", "gone", None, None),
])
def test_the_captured_screens_are_read_as_measured(name, ask, kind, qidx, cursor):
    run_ = driver._Run(asked_from(ask), [], None, None)

    async def capture() -> str:
        return fixture_text(name)

    run_.capture = capture
    screen = asyncio.run(run_.observe())
    assert (screen.kind, screen.qidx, screen.cursor) == (kind, qidx, cursor)


def test_the_review_of_a_partial_fill_is_refused_until_every_question_shows():
    run_ = driver._Run(asked_from("ask-3q-wide"), [QuestionAnswer(option="OAuth")] * 3, None, None)
    run_.screen = driver.Screen("review", fixture_text("58-review-q2-unanswered-other-answer"))
    with pytest.raises(AnswerRefused) as exc:
        asyncio.run(run_.review_and_submit())
    assert exc.value.reason == "review_mismatch"



def test_the_last_valid_ask_wins_over_a_malformed_one():
    good = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_ok", "name": "AskUserQuestion",
                                                          "input": json.loads((FIX / "ask-3q.json").read_text())}]}}
    bad = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_bad", "name": "AskUserQuestion",
                                                         "input": {"__unparsedToolInput": {"raw": "{"}}}]}}
    found = questions_in_lines([json.dumps(good).encode(), json.dumps(bad).encode()])
    assert found is not None and found.tool_use_id == "toolu_ok" and len(found.questions) == 3
    assert questions_in_lines([json.dumps(bad).encode()]) is None


def test_the_served_fields_match_the_pane_or_say_why_not():
    dialog = extract_dialog(fixture_text("11-multi3-q2of3-via-right"), "claude")
    got = serve_fields(dialog, THREE, True)
    assert got["questions_state"] == "matched" and got["question_index"] == 2 and got["question_total"] == 3
    assert got["questions_fingerprint"] == THREE.fingerprint and len(got["questions"]) == 3
    assert got["questions"][1]["options"][0] == {"label": "Cheese", "description": "melty", "preview": None}
    other = AskQuestions("t", parse_questions_input({"questions": [{"question": "Different?", "options": [{"label": "A"}]}]}))
    assert serve_fields(dialog, other, True) == {"questions": [], "questions_fingerprint": None, "questions_state": "mismatch"}
    assert serve_fields(dialog, None, False)["questions_state"] == "no_transcript"
    assert serve_fields(dialog, None, True)["questions_state"] == "no_questions"
    permission = extract_dialog("Do you want to proceed?\n  ❯ 1. Yes\n    2. No\n\n Esc to cancel", "claude")
    assert permission is None or serve_fields(permission, THREE, True) == {}



class FakeManager:

    def __init__(self, pane: AskPane) -> None:
        self.pane = pane

    def tmux_socket_name(self) -> str:
        return "test-socket"

    async def send_input(self, data: str, session_id: str) -> None:
        await self.pane.send(data)


def deliver(monkeypatch, pane: AskPane, fingerprint: str, located: bool = True) -> str:
    from types import SimpleNamespace

    from src.core.approvals import deliver as deliver_mod

    monkeypatch.setattr(deliver_mod, "locate_ask", lambda info, watcher: (THREE, located))
    monkeypatch.setattr(deliver_mod.AttentionEvidenceReader, "_capture", staticmethod(lambda socket, name, lines: pane.render()))
    info = SimpleNamespace(tmux_session="carnivore_x", session=SimpleNamespace(id="ses_1"))
    return asyncio.run(deliver_mod.deliver_answers(manager=FakeManager(pane), watcher=None, info=info,
                                                   questions_fingerprint=fingerprint, answers=ANSWERS, source="owner"))


def test_the_delivery_submits_the_ask_the_caller_saw(monkeypatch):
    pane = pane_for(THREE)
    assert deliver(monkeypatch, pane, THREE.fingerprint) == "review" and pane.submitted is not None


@pytest.mark.parametrize("fingerprint,located,reason", [
    ("0" * 64, True, "questions_changed"),
    (THREE.fingerprint, False, "no_transcript_questions"),
])
def test_a_stale_ask_or_a_missing_transcript_presses_nothing(monkeypatch, fingerprint, located, reason):
    pane = pane_for(THREE)
    with pytest.raises(AnswerRefused) as exc:
        deliver(monkeypatch, pane, fingerprint, located)
    assert exc.value.reason == reason and pane.keys == []



def test_the_mcp_card_shows_the_typed_text_redacted():
    from src.core.mcp import dialog_tools

    body = dialog_tools._batch_body({"target": "x", "questions_fingerprint": "a" * 64,
                                     "answers": [{"option": "Green"}, {"options": ["Cheese"], "other": "plain words"}]})
    shown = dialog_tools._shown_batch(body)
    assert shown["answers"][1] == {"options": ["Cheese"], "other": "plain words"}


@pytest.mark.parametrize("args", [
    {"questions_fingerprint": "a" * 64, "answers": [{"other": "a\x1bb"}]},
    {"questions_fingerprint": "a" * 64, "answers": []},
    {"questions_fingerprint": "short", "answers": [{"option": "x"}]},
    {"questions_fingerprint": "a" * 64, "answers": [{"option": "x", "extra": 1}]},
])
def test_the_batch_body_refuses_control_characters_and_junk(args):
    from src.core.mcp import dialog_tools
    from src.core.mcp.common import ToolError

    with pytest.raises(ToolError):
        dialog_tools._batch_body({"target": "x", **args})


def test_the_transcript_file_is_read_from_its_tail_and_the_located_path_is_reused(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.core.approvals import ask_questions
    from src.core.session_transcript_presence import CONVERSATION_PRESENT

    record = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_9", "name": "AskUserQuestion",
                                                            "input": json.loads((FIX / "ask-3q.json").read_text())}]}}
    path = tmp_path / "c.jsonl"
    path.write_text("x" * 5000 + "\n" + json.dumps(record) + "\n" + json.dumps({"type": "user"}) + "\n")
    monkeypatch.setattr(ask_questions, "TAIL_BYTES", 3000)
    seen = []
    from src.core.session_token_usage import claude_reader
    monkeypatch.setattr(claude_reader, "locate_transcript", lambda uuid, working_dir=None: seen.append(uuid) or SimpleNamespace(
        outcome=CONVERSATION_PRESENT, path=path))
    info = SimpleNamespace(claude_session_uuid="u-1", session=SimpleNamespace(id="ses_1", working_dir="/x"))
    ask_questions._PATHS.clear()
    asked, located = ask_questions.locate_ask(info, None)
    assert located and asked.tool_use_id == "toolu_9" and asked.fingerprint != THREE.fingerprint
    assert ask_questions.locate_ask(info, None)[0] is asked and seen == ["u-1"]



def test_notes_on_the_first_option_of_a_preview_question_still_select_it():
    preview = asked_from("ask-preview")
    pane = pane_for(preview)
    run(pane, preview, [QuestionAnswer(option="Grid", notes="dense only"), QuestionAnswer(option="Safe")])
    assert pane.notes == {0: "dense only"} and pane.submitted[0] == ("opt", 0)
    assert pane.keys[:5] == [DOWN, UP, "n", "dense only", ENTER] and pane.stray == []


def test_old_notes_are_not_submitted_with_an_answer_that_sent_none():
    preview = asked_from("ask-preview")
    pane = pane_for(preview)
    pane.notes[0] = "left over"
    assert refused(pane, preview, [QuestionAnswer(option="List"), QuestionAnswer(option="Safe")]) == "notes_not_empty"
    assert pane.submitted is None and ENTER not in pane.keys


def test_a_review_line_in_the_scrollback_does_not_hide_a_live_question(monkeypatch):
    monkeypatch.setattr("tests.python.approvals.ask_pane_sim.HISTORY", ["Ready to submit your answers?", "⏺ working"])
    pane = pane_for(THREE, tab=1)
    assert run(pane) == "review" and pane.submitted is not None


def test_the_review_is_read_from_its_last_line_not_from_scrollback():
    from src.core.approvals.extract import extract_review

    text = "Ready to submit your answers?\n  1. Old thing\n  2. Older\n" + fixture_text("26-review-all-answered")
    review = extract_review(text)
    assert review is not None and review.index_of("Submit answers") == 0 and review.index_of("Old thing") is None


def test_a_redraw_back_to_a_question_after_the_final_enter_is_not_a_submission():
    pane = pane_for(THREE)

    def back(p: AskPane) -> None:
        if p.submitted is not None and p.keys[-1] == ENTER:
            p.submitted = None
            p.arrive(0)
    pane.after_key = back
    assert refused(pane) == "submit_not_confirmed" and pane.keys.count(ENTER) == 4


def blank_then_dialog(pane: AskPane) -> List[str]:
    reads: List[str] = []
    real = pane.capture

    async def blip() -> str:
        if pane.submitted is not None and not reads:
            reads.append("blank")
            text = pane.render()
            pane.submitted = None
            pane.arrive(0)
            return text
        return await real()
    pane.capture = blip
    return reads


def test_a_landed_submit_is_never_reported_as_a_failure_even_when_a_blank_frame_is_followed_by_the_dialog():
    pane = pane_for(THREE)
    reads = blank_then_dialog(pane)
    assert run(pane) == "review" and reads == ["blank"] and pane.keys.count(ENTER) == 4


def test_a_lone_single_select_blank_frame_then_the_dialog_is_still_a_landed_submit():
    one = AskQuestions("t", parse_questions_input({"questions": [{"question": "Pick a fruit?", "header": "Fruit", "multiSelect": False,
                                                                  "options": [{"label": "Apple"}, {"label": "Banana"}]}]}))
    pane = pane_for(one)
    reads = blank_then_dialog(pane)
    assert run(pane, one, [QuestionAnswer(option="Banana")]) == "direct" and reads == ["blank"]
    assert pane.keys.count(ENTER) == 1


def test_one_failed_capture_after_the_final_enter_does_not_turn_a_landed_submit_into_a_refusal():
    pane = pane_for(THREE)
    real, hits = pane.capture, []

    async def flaky() -> str:
        if pane.submitted is not None and not hits:
            hits.append(1)
            return None
        return await real()
    pane.capture = flaky
    assert run(pane) == "review" and hits == [1] and pane.keys.count(ENTER) == 4


def test_a_lone_single_select_whose_ask_stays_on_screen_is_submit_not_confirmed():
    one = AskQuestions("t", parse_questions_input({"questions": [{"question": "Pick a fruit?", "header": "Fruit", "multiSelect": False,
                                                                  "options": [{"label": "Apple"}, {"label": "Banana"}]}]}))
    pane = pane_for(one)
    pane.press = lambda key: None
    pane.cursor = 1
    with pytest.raises(AnswerRefused) as exc:
        asyncio.run(driver._Run(one, [QuestionAnswer(option="Banana")], pane.capture, pane.send).submit())
    assert exc.value.reason == "submit_not_confirmed" and pane.keys == [ENTER]


def test_a_startup_screen_is_never_answered(monkeypatch):
    trust = (Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens" / "trust_dialog.txt").read_text()
    pane = pane_for(THREE)
    pane.override = trust
    assert refused(pane) == "dialog_changed" and pane.keys == []



def test_a_review_that_shows_another_answer_than_the_one_filled_is_refused_before_the_submit():
    pane = pane_for(THREE)

    def swap(p: AskPane) -> None:
        if p.tab == p.n and 0 in p.sel:
            p.sel[0] = ("opt", 0)
    pane.after_key = swap
    assert refused(pane) == "review_mismatch"
    assert pane.submitted is None and pane.keys.count(ENTER) == 3


def test_a_typed_multi_select_other_row_that_does_not_tick_stops_the_run():
    pane = pane_for(THREE, tab=1)

    def untick(p: AskPane) -> None:
        if p.tab == 1 and p.keys[-1] == "Corn":
            p.sel[1]["other_on"] = False
    pane.after_key = untick
    assert refused(pane) == "dialog_changed"
    assert pane.submitted is None and pane.keys[-1] == "Corn"


class DeafEnterPane(AskPane):

    deaf = 0

    def press(self, key: str) -> None:
        if key == ENTER and self.tab == self.deaf:
            return
        super().press(key)


@pytest.mark.parametrize("deaf", [0, 2], ids=["first_question", "last_question"])
def test_an_enter_that_changed_nothing_is_key_not_applied_not_whatever_screen_shows(deaf):
    DeafEnterPane.deaf = deaf
    pane = DeafEnterPane([{"question": q.question, "header": q.header, "multiSelect": q.multi_select,
                           "options": [{"label": o.label, "description": o.description} for o in q.options]} for q in THREE.questions])
    assert refused(pane) == "key_not_applied" and pane.keys[-1] == ENTER and pane.keys.count(ENTER) == deaf + 1


def test_a_box_ticked_by_another_client_during_a_toggle_stops_the_run():
    pane = pane_for(THREE, tab=1)

    def extra(p: AskPane) -> None:
        if p.tab == 1 and p.keys[-1] == " " and p.sel[1]["ticks"] == {0}:
            p.sel[1]["ticks"].add(1)
    pane.after_key = extra
    assert refused(pane) == "dialog_changed"
    assert pane.submitted is None and pane.keys.count(" ") == 1


def test_a_box_ticked_by_another_client_during_the_other_text_stops_the_run():
    pane = pane_for(THREE, tab=1)
    answers = [ANSWERS[0], QuestionAnswer(options=("Cheese",), other="Corn"), ANSWERS[2]]

    def extra(p: AskPane) -> None:
        if p.tab == 1 and p.keys[-1] == "Corn":
            p.sel[1]["ticks"].add(1)
    pane.after_key = extra
    assert refused(pane, answers=answers) == "dialog_changed"
    assert pane.submitted is None and pane.keys[-1] == "Corn"



ONE = AskQuestions("t", parse_questions_input({"questions": [{"question": "Pick a fruit?", "header": "Fruit", "multiSelect": False,
                                                              "options": [{"label": "Apple"}, {"label": "Banana"}]}]}))


def after_enter_shows(pane: AskPane, text: str) -> None:
    real = pane.capture

    async def shown() -> str:
        return text if pane.submitted is not None else await real()
    pane.capture = shown


def test_a_half_drawn_frame_of_the_same_ask_after_the_enter_is_never_a_submission():
    pane = pane_for(THREE)
    after_enter_shows(pane, pane_for(THREE, tabs_shown=4).render())
    assert refused(pane) == "submit_not_confirmed" and pane.keys.count(ENTER) == 4


def test_a_different_dialog_after_the_enter_counts_as_submitted():
    pane = pane_for(ONE)
    after_enter_shows(pane, "Do you want to proceed?\n  1. Yes\n  2. No\nEsc to cancel")
    assert run(pane, ONE, [QuestionAnswer(option="Banana")]) == "direct" and pane.keys.count(ENTER) == 1


def test_left_is_never_pressed_with_the_cursor_inside_a_typed_other_row():
    pane = pane_for(THREE, tab=1)
    pane.cursor = pane.layout(1).index("other")
    pane.typed[1] = "old"
    assert refused(pane) == "other_row_not_empty" and pane.stray == []


def test_a_multi_select_other_row_already_ticked_is_not_submitted_when_no_text_was_asked_for():
    pane = pane_for(THREE, tab=1)
    pane.sel[1] = {"ticks": set(), "other_on": True}
    pane.typed[1] = "old"
    assert refused(pane, answers=[ANSWERS[0], QuestionAnswer(options=("Cheese",)), ANSWERS[2]]) == "other_row_not_empty"
    assert pane.submitted is None


@pytest.mark.parametrize("change", [lambda p: p.typed.update({1: "Xorn"}), lambda p: setattr(p, "cursor", p.cursor - 1)],
                         ids=["another_text", "cursor_moved"])
def test_a_typed_other_row_that_reads_another_text_or_moved_the_cursor_stops_the_run(change):
    pane = pane_for(THREE, tab=1)
    drift_after(pane, len(pane_keys_before_corn()), change)
    assert refused(pane) == "dialog_changed" and pane.submitted is None


def pane_keys_before_corn() -> List[str]:
    pane = pane_for(THREE, tab=1)
    run(pane)
    return pane.keys[:pane.keys.index("Corn") + 1]



def review_shows(pane: AskPane, edit) -> None:
    real = pane.capture

    async def shown() -> str:
        text = await real()
        return edit(text) if "Review your answers" in text else text
    pane.capture = shown


def test_an_empty_but_ticked_multi_select_other_row_is_refused_before_the_text_is_typed():
    pane = pane_for(THREE, tab=1)
    pane.sel[1] = {"ticks": set(), "other_on": True}
    assert refused(pane) == "other_row_not_empty"
    assert "Corn" not in pane.keys and pane.submitted is None


class DeafNotesPane(AskPane):

    def press(self, key: str) -> None:
        if key != "n":
            super().press(key)


def test_a_notes_key_that_did_not_open_the_entry_is_notes_not_opened_and_the_notes_are_never_typed():
    preview = asked_from("ask-preview")
    pane = DeafNotesPane([{"question": q.question, "header": q.header, "multiSelect": q.multi_select,
                           "options": [{"label": o.label, "description": o.description, **({"preview": o.preview} if o.preview else {})}
                                       for o in q.options]} for q in preview.questions])
    assert refused(pane, preview, [QuestionAnswer(option="List", notes="dense only"), QuestionAnswer(option="Safe")]) == "notes_not_opened"
    assert "dense only" not in pane.keys


@pytest.mark.parametrize("skip,edit", [
    (True, lambda t: t.replace("⚠ You have not answered all questions\n", "")),
    (False, lambda t: t.replace("Review your answers\n", "Review your answers\n⚠ You have not answered all questions\n")),
], ids=["skipped_but_no_warning", "warning_but_nothing_skipped"])
def test_a_review_whose_warning_disagrees_with_what_was_left_out_is_refused_before_the_submit(skip, edit):
    pane = pane_for(THREE)
    review_shows(pane, edit)
    answers = [ANSWERS[0], QuestionAnswer(), ANSWERS[2]] if skip else ANSWERS
    assert refused(pane, THREE, answers) == "review_mismatch"
    assert pane.submitted is None and pane.keys.count(ENTER) == (2 if skip else 3)


def test_a_review_that_lists_one_more_answer_than_was_filled_is_refused_before_the_submit():
    pane = pane_for(THREE)
    review_shows(pane, lambda t: t.replace("Ready to submit your answers?", " ● Another question?\n   → x\nReady to submit your answers?"))
    assert refused(pane) == "review_mismatch" and pane.submitted is None and pane.keys.count(ENTER) == 3


def test_a_review_that_quotes_and_escapes_typed_text_still_matches_the_answer():
    typed = 'a  b \U0001f525 "q" \\ end'
    shown = 'Cheese, "a  b \U0001f525 \\"q\\" \\\\ end"'
    assert driver._review_matches(shown, f"Cheese, {typed}", True)
    assert driver._review_matches(json.dumps(typed, ensure_ascii=False), typed, False)
    assert not driver._review_matches('Cheese, "other"', f"Cheese, {typed}", True)
