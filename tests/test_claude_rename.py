
import pytest

from src.core.claude_rename import (
    MAX_NAME_CHARS,
    MIN_RENAME_VERSION,
    PUSH_DEFERRED,
    PUSH_SENT,
    PUSH_UNSUPPORTED,
    decide_push,
    oob_rename_argv,
    launch_name_args,
    name_is_pushable,
    parse_claude_version,
    rename_command,
    supports_rename,
)

VER = (2, 1, 248)



@pytest.mark.parametrize(
    "text,expected",
    [
        ("2.1.248 (Claude Code)", (2, 1, 248)),
        ("2.1.248", (2, 1, 248)),
        ("  2.1.205 (Claude Code)\n", (2, 1, 205)),
        ("not a version", None),
        ("2.1", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_claude_version(text, expected):
    assert parse_claude_version(text) == expected


def test_unknown_version_is_treated_as_unsupported():
    assert supports_rename(None) is False
    assert supports_rename((2, 1, MIN_RENAME_VERSION[2] - 1)) is False
    assert supports_rename(MIN_RENAME_VERSION) is True



def test_a_newline_is_never_pushable():
    assert name_is_pushable("first\nsecond") is False
    assert name_is_pushable("carriage\rreturn") is False


def test_names_claude_would_rewrite_are_refused():
    assert name_is_pushable("x" * MAX_NAME_CHARS) is True
    assert name_is_pushable("x" * (MAX_NAME_CHARS + 1)) is False
    assert name_is_pushable("") is False
    assert name_is_pushable("   ") is False
    assert name_is_pushable("bell\x07here") is False


def test_ordinary_names_including_spaces_and_emoji_are_pushable():
    assert name_is_pushable("Refactor spike (round 2)") is True
    assert name_is_pushable("Refactor spike 🚀") is True



def _d(**kw):
    base = dict(
        label="X", claude_uuid="u1", claude_version=VER, is_claude_session=True
    )
    base.update(kw)
    return decide_push(**base)


def test_a_bound_conversation_gets_the_rename():
    outcome, reason = _d()
    assert outcome == PUSH_SENT
    assert "out of band" in reason


def test_no_activity_gate_exists_any_more():
    import inspect

    params = set(inspect.signature(decide_push).parameters)
    assert "activity_status" not in params
    assert "hooks_seen" not in params
    assert params == {
        "label",
        "claude_uuid",
        "claude_version",
        "is_claude_session",
        "transcript_presence",
    }




def test_a_measured_absent_transcript_defers_the_push():
    from src.core.session_transcript_presence import CONVERSATION_ABSENT

    outcome, reason = _d(transcript_presence=CONVERSATION_ABSENT)

    assert outcome == PUSH_DEFERRED
    assert "transcript" in reason


def test_an_unchecked_transcript_still_sends():
    from src.core.session_transcript_presence import CONVERSATION_UNCHECKED

    assert _d(transcript_presence=CONVERSATION_UNCHECKED)[0] == PUSH_SENT
    assert _d(transcript_presence=None)[0] == PUSH_SENT


def test_a_present_transcript_sends():
    from src.core.session_transcript_presence import CONVERSATION_PRESENT

    assert _d(transcript_presence=CONVERSATION_PRESENT)[0] == PUSH_SENT


def test_a_failed_spawn_is_reported_rather_than_swallowed():
    from src.core.claude_rename import spawn_oob_rename

    assert (
        spawn_oob_rename(
            ["/nonexistent/claude-binary-that-is-not-there", "-p"],
            session_id="ses_test",
        )
        is False
    )


def test_a_spawn_that_starts_reports_true_and_reaps_the_child():
    import time

    from src.core.claude_rename import spawn_oob_rename

    assert spawn_oob_rename(["/usr/bin/true"], session_id="ses_test") is True
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if threading_named("oob-rename-ses_test") is None:
            break
        time.sleep(0.02)
    assert threading_named("oob-rename-ses_test") is None


def threading_named(name):
    import threading

    for thread in threading.enumerate():
        if thread.name == name:
            return thread
    return None


def test_an_unbound_conversation_defers_because_resume_needs_a_uuid():
    outcome, reason = _d(claude_uuid=None)
    assert outcome == PUSH_DEFERRED
    assert "uuid" in reason


def test_non_claude_and_old_claude_are_unsupported_not_deferred():
    outcome, _ = _d(is_claude_session=False)
    assert outcome == PUSH_UNSUPPORTED
    outcome, reason = _d(claude_version=(2, 1, 100))
    assert outcome == PUSH_UNSUPPORTED
    assert "2.1.205" in reason


def test_an_unpushable_name_defers_rather_than_sending_a_different_one():
    outcome, reason = _d(label="bad\nname")
    assert outcome == PUSH_DEFERRED
    assert "disagree" in reason


def test_the_argv_is_a_list_so_no_shell_ever_parses_the_label():
    argv = oob_rename_argv("/usr/bin/claude", "uuid-1", 'evil"; $(rm -rf /) #')
    assert isinstance(argv, list)
    assert argv[:4] == ["/usr/bin/claude", "-p", "--resume", "uuid-1"]
    assert argv[4].startswith("/rename ")
    assert argv[4].endswith('evil"; $(rm -rf /) #')
    assert len(argv) == 5


def test_rename_command_is_the_literal_line():
    assert rename_command("My Session") == "/rename My Session"



def test_launch_name_args_only_for_the_claude_family():
    assert launch_name_args(label="S", family="claude", claude_version=VER) == ["--name", "S"]
    for family in ("codex", "hermes", "openclaw", "shell", "local", None):
        assert launch_name_args(label="S", family=family, claude_version=VER) == []


def test_launch_name_args_degrade_to_empty_never_raise():
    assert launch_name_args(label=None, family="claude", claude_version=VER) == []
    assert launch_name_args(label="S", family="claude", claude_version=None) == []
    assert launch_name_args(label="S", family="claude", claude_version=(2, 1, 1)) == []
    assert launch_name_args(label="bad\nname", family="claude", claude_version=VER) == []



def test_launch_name_args_for_resolves_the_family_that_will_run():
    from src.core.claude_rename import launch_name_args_for_agent_type as _launch_name_args_for

    assert _launch_name_args_for(label=None, agent_type="claude") == []

    got = _launch_name_args_for(label="Spike", agent_type="claude")
    assert got in ([], ["--name", "Spike"]), (
        "either the local claude supports --name and we pass it, or it "
        "does not and we pass nothing - never anything else"
    )

    for family in ("codex", "hermes", "openclaw", "shell"):
        assert _launch_name_args_for(label="Spike", agent_type=family) == []


def test_an_unknown_agent_type_still_gets_the_flag_and_that_is_correct():
    from src.core.agent_families import get_family
    from src.core.claude_rename import launch_name_args_for_agent_type as _l

    for junk in ("no-such-agent-type", None):
        assert get_family(junk).name == "claude"
        assert _l(label="S", agent_type=junk) in ([], ["--name", "S"])

    assert get_family("shell").name == "shell"
    assert _l(label="S", agent_type="shell") == []
