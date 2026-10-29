
from __future__ import annotations

from pathlib import Path

from src.core.approvals.extract import extract_dialog, extract_review
from src.core.attention.codex_pane import classify_codex_pane
from src.core.attention.pane_markers import classify_pane_tail

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "approvals"


def screen(name: str) -> str:
    return (FIX / f"{name}.txt").read_text()


def test_claude_single_question_is_extracted_and_now_detected():
    d = extract_dialog(screen("claude_single"), "claude")
    assert (d.kind, d.question, d.options, d.cursor) == ("ask_user_question", "Pick a colour?", ("Red", "Blue"), 0)
    assert d.has_other and not d.multi_select
    assert classify_pane_tail(screen("claude_single").splitlines()).question_dialog is True


def test_claude_multi_select_rows_and_checked_state():
    d = extract_dialog(screen("claude_multi"), "claude")
    assert d.multi_select and d.options == ("Cheese", "Ham", "Olives")
    assert [r.checked for r in d.rows[:3]] == [False, False, False]
    assert d.index_of_role("submit") is not None


def test_multi_question_screen_still_detected():
    d = extract_dialog(screen("claude_multi_question"), "claude")
    assert d.question == "Pick a colour?" and d.options == ("Red", "Blue")


def test_claude_permission_dialog():
    d = extract_dialog(screen("claude_permission"), "claude")
    assert d.kind == "permission" and d.question == "Do you want to proceed?"
    assert d.options[0] == "Yes" and d.options[-1] == "No" and "touch rigfile" in d.body


def test_codex_command_approval_and_case_insensitive_detection():
    text = screen("codex_command")
    d = extract_dialog(text, "codex")
    assert d.kind == "codex_approval" and d.question == "Would you like to run the following command?"
    assert d.options[0] == "Yes, proceed" and d.cursor == 0
    assert classify_codex_pane(text).approval_dialog is True
    grant = "  Would you like to grant these permissions?\n"
    assert classify_codex_pane(grant).approval_dialog is True


def test_fingerprint_ignores_cursor_and_checkbox_state_but_not_the_question():
    base = screen("claude_multi")
    moved = base.replace("❯ 1. [ ] Cheese", "  1. [ ] Cheese").replace("  2. [ ] Ham", "❯ 2. [✔] Ham")
    a, b = extract_dialog(base, "claude"), extract_dialog(moved, "claude")
    assert (a.cursor, b.cursor) == (0, 1) and b.rows[1].checked is True
    assert a.fingerprint == b.fingerprint
    assert extract_dialog(base.replace("Which toppings?", "Which drinks?"), "claude").fingerprint != a.fingerprint


def test_no_dialog_and_prose_are_none():
    assert extract_dialog("❯ hello\n  1. a list\n  2. in prose\n", "claude") is None
    assert extract_dialog("", "codex") is None


def test_review_screen_after_submit_is_read_apart():
    pane = ("←  ☒ Top  ✔ Submit  →\n\nReview your answers\n\n ● Which toppings?\n   → Cheese, Olives\n\n"
            "Ready to submit your answers?\n\n❯ 1. Submit answers\n  2. Cancel\n")
    d = extract_review(pane)
    assert d.options == ("Submit answers", "Cancel") and d.cursor == 0
    assert extract_dialog(pane, "claude") is None and extract_review("nothing") is None



WIDTHS = (40, 50, 60, 80)


def wide(tag: str, family: str):
    return {w: extract_dialog(screen(f"wrap_{tag}_{w}"), family) for w in WIDTHS}


def test_wrapped_ask_multi_and_codex_keep_one_fingerprint_at_every_width():
    for tag, family in (("ask", "claude"), ("multi", "claude"), ("codex", "codex")):
        got = wide(tag, family)
        assert all(got.values()), (tag, [w for w, d in got.items() if not d])
        assert len({d.fingerprint for d in got.values()}) == 1, tag
        assert all(d.cursor == 0 for d in got.values())
        assert len({d.question for d in got.values()}) == 1 or len({d.question.replace("│", "") for d in got.values()}) == 1


def test_wrapped_ask_reads_the_whole_question_and_options():
    d = wide("ask", "claude")[40]
    assert d.question == "Which deployment environment should the release candidate be promoted to first this week?"
    assert d.options == ("Staging cluster in the east region", "Production canary at five percent")
    assert d.has_other and not d.multi_select
    m = wide("multi", "claude")[40]
    assert m.multi_select and m.options == ("Extra mozzarella cheese", "Smoked ham and pineapple", "Black olives")
    assert m.index_of_role("submit") is not None


def test_wrapped_codex_hint_and_long_option_are_one_row():
    d = wide("codex", "codex")[40]
    assert d.kind == "codex_approval" and d.question == "Would you like to run the following command?"
    assert len(d.rows) == 3 and d.options[0] == "Yes, proceed"
    assert d.rows[2].key == wide("codex", "codex")[80].rows[2].key


def test_wrapped_permission_is_read_at_every_width_and_stable_from_50():
    got = wide("bash", "claude")
    assert all(d and d.kind == "permission" and d.question == "Do you want to proceed?" for d in got.values())
    assert len({got[w].fingerprint for w in (50, 60, 80)}) == 1


def test_label_from_another_width_still_finds_its_row():
    full = wide("bash", "claude")[80].options[1]
    for w in WIDTHS:
        assert wide("bash", "claude")[w].index_of(full) == 1, w
    assert wide("bash", "claude")[40].index_of("Yes") == 0
    assert wide("bash", "claude")[80].index_of("Yes, and always allow access to") == 1
    assert wide("bash", "claude")[80].index_of("Ye") is None


def test_wrapped_footer_alone_is_not_a_dialog_without_rows():
    assert extract_dialog("Enter to select · ↑/↓ to navigate · Esc\nto cancel\n", "claude") is None


def test_wrapped_dialogs_are_still_detected_as_dialogs_at_every_width():
    for w in WIDTHS:
        for tag in ("ask", "multi", "bash"):
            assert classify_pane_tail(screen(f"wrap_{tag}_{w}").splitlines()).shows_dialog is True, (tag, w)
        assert classify_codex_pane(screen(f"wrap_codex_{w}")).approval_dialog is True, w



def test_permission_screens_differing_only_in_the_command_get_different_fingerprints():
    base = screen("claude_permission")
    other = base.replace("   touch rigfile\n", "   rm -rf build\n")
    assert other != base
    assert extract_dialog(other, "claude").fingerprint != extract_dialog(base, "claude").fingerprint
    cx = screen("codex_command")
    assert extract_dialog(cx.replace("$ touch rigfile", "$ rm -rf build"), "codex").fingerprint != \
        extract_dialog(cx, "codex").fingerprint


def test_fingerprint_ignores_the_cursor_on_a_body_bound_dialog():
    base = screen("claude_permission")
    moved = base.replace("❯ 1. Yes", "  1. Yes").replace("  4. No", "❯ 4. No")
    assert extract_dialog(moved, "claude").cursor == 3
    assert extract_dialog(moved, "claude").fingerprint == extract_dialog(base, "claude").fingerprint


def test_same_command_keeps_one_fingerprint_at_50_60_and_80_columns():
    for tag, family in (("bash", "claude"), ("codex", "codex")):
        got = wide(tag, family)
        assert len({got[w].fingerprint for w in (50, 60, 80)}) == 1, tag
    assert len({d.fingerprint for d in wide("codex", "codex").values()}) == 1


def test_a_border_glyph_or_ansi_does_not_change_the_fingerprint():
    base = screen("claude_permission")
    noisy = base.replace("   touch rigfile\n", "  \x1b[1m│ touch rigfile\x1b[0m\n")
    assert extract_dialog(noisy, "claude").fingerprint == extract_dialog(base, "claude").fingerprint


def test_multi_question_tabs_and_numbered_descriptions_stay_with_their_option():
    d = extract_dialog(screen("claude_multi_question_numbered_desc"), "claude")
    assert d.options == ("Hackers", "The Matrix", "Sneakers", "WarGames")
    assert [r.description for r in d.rows[:4]] == [
        "1995. Hack the planet.", "1999. There is no spoon.", "1992. Too many secrets.", "1983. Shall we play a game?"]
    assert [r.role for r in d.rows[4:]] == ["other", "chat"]
    assert (d.question_index, [t.title for t in d.tabs], [t.answered for t in d.tabs]) == (
        1, ["Movie", "Playlist", "Fuel"], [False, False, False])
    out = d.to_dict()
    assert out["question_total"] == 3 and out["tabs"][0] == {"title": "Movie", "answered": False}


def test_next_question_is_a_new_fingerprint_and_a_single_question_has_no_tabs():
    first = screen("claude_multi_question_numbered_desc")
    second = first.replace("☐ Movie", "☒ Movie")
    a, b = extract_dialog(first, "claude"), extract_dialog(second, "claude")
    assert (b.question_index, a.fingerprint != b.fingerprint) == (2, True)
    single = extract_dialog(screen("claude_single"), "claude")
    assert single.tabs == () and single.question_index is None and single.to_dict()["question_total"] is None


_Q2 = """\
{rule}
←  {a} Movie  {b} Bands  ☐ Fuel  ✔ Submit  →
Which bands?
❯ 1. [{box}] Pantera
         1990. Cowboys from Hell.
  2. [ ] Slayer
         1986. Reign in Blood.
  3. [ ] Type something
     Next
{rule}
  4. Chat about this
Enter to select · Tab/Arrow keys to navigate · Esc to cancel
""".replace("{rule}", "─" * 60)


def test_ticked_multi_select_keeps_its_own_tab_as_the_visible_question():
    fresh = extract_dialog(_Q2.format(a="☒", b="☐", box=" "), "claude")
    ticked = extract_dialog(_Q2.format(a="☒", b="☒", box="✔"), "claude")
    assert (fresh.question_index, ticked.question_index) == (2, 2)
    assert fresh.fingerprint == ticked.fingerprint


def test_plan_approval_has_no_esc_footer_and_is_still_a_dialog():
    d = extract_dialog(screen("claude_plan_narrow"), "claude")
    assert d is not None and d.kind == "plan_approval"
    assert d.options == ("Yes, and switch to BYPASS PERMISSIONS", "Yes, manually approve edits", "Tell Claude what to change")


def test_wrapped_four_question_tab_strip_keeps_tabs_and_step():
    base = screen("wrap_multi_40")
    wrapped = base.replace("←  ☐ Top  ✔ Submit  →", "←  ☒ Colour  ☒ Size  ☒ Movie  ☐ Band\n✔ Submit  →")
    d = extract_dialog(wrapped, "claude")
    assert (d.question_index, len(d.tabs)) == (4, 4)
    third = extract_dialog(wrapped.replace("☒ Movie  ☐ Band", "☐ Movie  ☐ Band"), "claude")
    assert (third.question_index, len(third.tabs)) == (3, 4) and third.fingerprint != d.fingerprint


def test_long_question_scrolled_above_a_short_pane_is_read_whole_with_its_tabs():
    viewport, scrolled = screen("claude_long_question_viewport"), screen("claude_long_question_scrolled")
    from src.core.approvals.extract import extract_dialog_scrolled
    d = extract_dialog_scrolled(viewport, "claude", lambda: scrolled)
    assert d.question.startswith("#148 modified files rail: the issue says read git inside the session-listing pass.")
    assert d.question.endswith("Deviate from the issue?")
    assert [t.title for t in d.tabs] == ["Git reads", "Changed =", "Rail spot", "First theme"] and d.question_index == 1
    assert d.options == ("Read on view, push (Recommended)", "Listing pass, as written", "Browser polls every 10s")
    assert extract_dialog_scrolled("no dialog here", "claude", lambda: scrolled) is None


def test_options_with_a_preview_box_and_answered_tabs_parse():
    d = extract_dialog(screen("claude_preview_options"), "claude")
    assert (d.kind, d.question, d.cursor) == ("ask_user_question", "Where does the changes rail live?", 0)
    assert d.options == ("Right column in the cell (Recommended)", "Drawer tab", "Footer chip + popover")
    assert [r.description for r in d.rows if r.role == "option"] == ["", "", ""]
    assert [(t.title, t.answered) for t in d.tabs][:3] == [("Git reads", True), ("Changed =", True), ("Rail spot", False)]
    assert d.question_index == 3 and d.index_of_role("chat") == 3


def test_autodeny_countdown_does_not_change_the_fingerprint_but_the_command_does():
    raw = screen("claude_workflow_autodeny_clock")
    a, b = (extract_dialog(raw.replace("@@", clock), "claude") for clock in ("1:59", "1:57"))
    assert a.kind == "permission" and a.fingerprint == b.fingerprint
    other = extract_dialog(raw.replace("@@", "1:59").replace("rm -f .tok/*;", "rm -rf /;"), "claude")
    assert other.fingerprint != a.fingerprint


def test_a_first_option_with_a_seven_line_wrapped_description_keeps_all_its_rows_and_its_question():
    dialog = extract_dialog(screen("multiq/61-long-description-120col"), "claude")
    assert dialog is not None
    assert [r.role for r in dialog.rows] == ["option", "option", "other", "chat"]
    assert dialog.question.startswith("Which of these really long options?") and dialog.question.endswith("QEND")


def test_a_numbered_list_inside_an_indented_bash_command_is_not_taken_for_the_first_option():
    body = "\n".join(f"   {n}. submit item {n}" for n in range(1, 11))
    pane = (
        " Bash command\n\n"
        "   git commit -m \"$(cat <<'EOF'\n"
        "   release notes\n"
        "   1. first change\n   2. second change\n"
        f"{body}\n"
        "   EOF\n   )\"\n   commit it\n\n"
        " Do you want to proceed?\n"
        " ❯ 1. Yes\n"
        "   2. Yes, and always allow access to /tmp/work from this project\n"
        "   3. No\n\n"
        " Esc to cancel · Tab to amend\n"
    )
    dialog = extract_dialog(pane, "claude")
    assert dialog is not None
    assert [r.label for r in dialog.rows] == ["Yes", "Yes, and always allow access to /tmp/work from this project", "No"]
    assert dialog.cursor == 0


def test_a_numbered_list_inside_an_option_description_is_not_taken_for_the_first_option():
    pane = (
        "────────────────────────────────────────────\n"
        "←  ☐ Approach  ✔ Submit  →\n\n"
        "│ Which approach?\n\n"
        "❯ 1. Option A\n"
        "     Steps, in order:\n"
        "     1. build it\n"
        "     2. test it\n"
        "  2. Option B\n"
        "     Skip the tests\n"
        "  3. Type something.\n"
        "────────────────────────────────────────────\n"
        "  4. Chat about this\n\n"
        "Enter to select · Tab/Arrow keys to navigate · Esc to cancel\n"
    )
    dialog = extract_dialog(pane, "claude")
    assert dialog is not None
    assert [r.label for r in dialog.rows] == ["Option A", "Option B", "Type something.", "Chat about this"]
    assert dialog.cursor == 0
    assert dialog.question.startswith("Which approach?")


def test_right_aligned_two_digit_rows_all_decode():
    rows = [f"{'❯' if n == 1 else ' '} {n:>2}. Opt{n}" for n in range(1, 13)]
    pane = (
        "────────────────────────────────────────────\n"
        "│ Pick one?\n\n" + "\n".join(rows) + "\n\n"
        "Enter to select · ↑/↓ to navigate · Esc to cancel\n"
    )
    dialog = extract_dialog(pane, "claude")
    assert dialog is not None
    assert [r.label for r in dialog.rows] == [f"Opt{n}" for n in range(1, 13)]
    assert dialog.cursor == 0


_FOOTERLESS_BLOCK = """\
 Do you want to allow Claude to fetch this
 content?
 ❯ 1. Yes
   2. Yes, and don't ask again for
      support.apple.com
   3. No, and tell Claude what to do
      differently (esc)
"""


def test_footerless_wrapped_permission_parses_and_loose_numbered_lists_do_not() -> None:
    pane = "output above\n" + "╌" * 44 + "\n" + _FOOTERLESS_BLOCK
    d = extract_dialog(pane, "claude")
    assert d is not None and d.kind == "permission"
    assert d.question == "Do you want to allow Claude to fetch this content?"
    assert len(d.options) == 3 and d.options[0] == "Yes"
    assert d.rows[1].key == "Yes,anddon'taskagainforsupport.apple.com"
    assert d.index_of("Yes, and don't ask again for support.apple.com") == 1
    assert d.cursor == 0
    assert extract_dialog(pane.replace("❯", " "), "claude") is None
    assert extract_dialog(pane + "more output\n", "claude") is None
