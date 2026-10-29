from __future__ import annotations

from pathlib import Path

from src.core.agent_fingerprint import detect_agent_type

FIXTURES = Path(__file__).parent / "fixtures" / "agent_captures"


def _load(fname: str) -> str:
    return (FIXTURES / fname).read_text(encoding="utf-8", errors="replace")




def test_real_capture_running_bypass_mode() -> None:
    assert detect_agent_type(_load("claude_running_bypass.txt")) == "claude"


def test_real_capture_running_manual_mode() -> None:
    assert detect_agent_type(_load("claude_running_manual_mode.txt")) == "claude"


def test_real_capture_narrow_terminal_truncated_footer() -> None:
    assert detect_agent_type(_load("claude_narrow_terminal.txt")) == "claude"


def test_real_capture_oauth_login_screen() -> None:
    assert detect_agent_type(_load("claude_login_oauth.txt")) == "claude"


def test_real_capture_verbose_transcript_view() -> None:
    assert detect_agent_type(_load("claude_verbose_transcript.txt")) == "claude"


def test_real_capture_partial_repaint_duplicated_banner() -> None:
    assert detect_agent_type(_load("claude_partial_repaint.txt")) == "claude"


def test_real_capture_plain_shell_mentioning_claude_is_none() -> None:
    assert detect_agent_type(_load("negative_plain_shell_mentions_claude.txt")) is None


def test_real_capture_blank_pane_is_none() -> None:
    assert detect_agent_type(_load("blank_pane.txt")) is None




def test_pattern_bypass_footer_alone_detects_claude() -> None:
    assert detect_agent_type("⏵⏵ bypass permissions on (shift+tab to cycle)") == "claude"


def test_pattern_manual_mode_footer_alone_detects_claude() -> None:
    assert detect_agent_type("⏸ manual mode on · ← for agents") == "claude"


def test_pattern_verbose_transcript_footer_alone_detects_claude() -> None:
    assert detect_agent_type(
        "Showing detailed transcript · ctrl+o to toggle · ↑↓ scroll"
    ) == "claude"


def test_pattern_oauth_url_alone_detects_claude() -> None:
    assert detect_agent_type(
        "https://claude.com/cai/oauth/authorize?code=true&client_id=x"
    ) == "claude"


def test_pattern_wide_box_banner_with_version_alone_detects_claude() -> None:
    assert detect_agent_type(
        "╭─── Claude Code v2.1.223 ───────────────────────────╮"
    ) == "claude"


def test_pattern_narrow_box_banner_without_version_alone_detects_claude() -> None:
    assert detect_agent_type("╭─ Claude Code ───────────────────────────╮") == "claude"


def test_pattern_compact_one_line_banner_alone_detects_claude() -> None:
    assert detect_agent_type(" ▐▛███▜▌   Claude Code v2.1.223") == "claude"


def test_pattern_box_banner_does_not_match_plain_prose_mentioning_claude_code() -> None:
    assert detect_agent_type(
        "The docs say Claude Code is a terminal tool, nothing box-drawn here."
    ) is None




def test_empty_returns_none() -> None:
    assert detect_agent_type("") is None
    assert detect_agent_type(None) is None


def test_unrelated_returns_none() -> None:
    assert detect_agent_type(
        "just some random TUI output\n$ ls\nfile.txt"
    ) is None


def test_banner_buried_under_noise_caught_only_by_second_pass() -> None:
    banner = "\U0001f99e OpenClaw something something boot line\n"
    noise = "\n".join(f"noise line {i}" for i in range(80))
    scrollback = banner + noise

    tail = "\n".join(scrollback.splitlines()[-50:])
    assert "OpenClaw" not in tail

    assert detect_agent_type(scrollback) == "openclaw"


def test_first_pass_window_is_actually_limited_to_last_50_lines() -> None:
    stale_openclaw_marker = "\U0001f99e OpenClaw something something boot line\n"
    noise = "\n".join(f"noise line {i}" for i in range(80))
    fresh_claude_marker = "\n⏵⏵ bypass permissions on"
    scrollback = stale_openclaw_marker + noise + fresh_claude_marker

    tail50 = "\n".join(scrollback.splitlines()[-50:])
    assert "OpenClaw" not in tail50

    assert detect_agent_type(scrollback) == "claude"


def test_box_drawing_frames_are_not_a_false_positive() -> None:
    junk = "\n".join(
        [
            "╭─ some box ─╮",
            "│ inner txt │",
            "╰────────────╯",
            "$ generic shell prompt",
        ]
    )
    assert detect_agent_type(junk) is None


def test_editor_buffer_listing_agent_names_in_prose_is_none() -> None:
    prose = "\n".join(
        [
            "  1  # Supported agent families",
            "  2  This tool detects Claude Code, Codex, Hermes and OpenClaw",
            "  3  sessions by fingerprinting their scrollback.",
            "  4  claude, codex, hermes, openclaw are the four keys.",
            "  5  # end of file",
        ]
    )
    assert detect_agent_type(prose) is None


def test_openclaw_banner_quoted_inside_claude_conversation_is_ambiguous_none() -> None:
    scrollback = (
        "╭─── Claude Code v2.1.223 ───╮\n"
        "│ user@example.com's Org      │\n"
        "╰──────────────────────────────╯\n"
        "❯ what's the openclaw banner look like again?\n"
        "⮕ Something like this: \U0001f99e OpenClaw\n"
        "⏵⏵ bypass permissions on\n"
    )
    assert detect_agent_type(scrollback) is None


def test_ambiguous_evidence_between_two_families_returns_none_not_a_coin_flip() -> None:
    scrollback = (
        "gpt-4 default fast · ~\n"
        "⏵⏵ bypass permissions on\n"
    )
    first = detect_agent_type(scrollback)
    second = detect_agent_type(scrollback)
    assert first is None
    assert second is None


def test_ambiguous_match_logs_a_warning_distinct_from_silent_absence() -> None:
    from structlog.testing import capture_logs

    scrollback = (
        "gpt-4 default fast · ~\n"
        "⏵⏵ bypass permissions on\n"
    )
    with capture_logs() as logs:
        assert detect_agent_type(scrollback) is None
    assert [e["event"] for e in logs] == ["agent_fingerprint_ambiguous_match"]
    assert logs[0]["log_level"] == "warning"

    with capture_logs() as logs:
        assert detect_agent_type("just some random TUI output\n$ ls\nfile.txt") is None
    assert logs == []
