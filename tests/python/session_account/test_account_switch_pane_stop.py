
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.account_switch import auto_restart, limit_detect

RULE = "─" * 78

ARGENT_COUNTDOWN = f"""\
⏺ Usage limit reached · continuing automatically at 1am · esc to cancel

✻ Churned for 11h 56m 20s · done 10:53 PM · 1 shell still running

{"─" * 40} Orbit-Draft ─
❯ 
{RULE}
  ⚠ Usage limit reached · limit resets 1am
    Continuing automatically at 1am · esc to cancel · /usage-credits to
    continue now
  \U0001f4e6/Nyedis/Code/Argent | Opus 5.5 (1M context) | 27% ~274k/1.0…
  ⏵⏵ bypass permissions on · 1 shell
"""

CV_UI_PAUSED = f"""\
✻ Waiting for 2 dynamic workflows to finish

{"─" * 40} Cv-UI ─
❯ 
{RULE}
  \U0001f4e6/My Projects/Cloude Code Repos/Dev/cloudecode | Opus 5.5 | 1…
  ⏵⏵ bypass permissions on (shift+tab to cycle)

  ⏸ superplan-wave5               paused · usage limit resets at 1am
  ⏸ admin-portal-own-site-passk…  paused · usage limit resets at 1am
"""

PROSE_ONLY = f"""\
  The log says ⚠ Usage limit reached · limit resets 1am and
  Continuing automatically at 1am · esc to cancel, so I read it.
  ⏸ superplan-wave5               paused · usage limit resets at 1am
  You've hit your weekly limit · resets 1am (America/New_York)

{"─" * 40} cloudecode-2 ─
❯ 
{RULE}
  \U0001f4e6/My Projects/Cloude Code Repos/Dev/cloudecode | Opus 5.5 | 12%
  ⏵⏵ bypass permissions on (shift+tab to cycle)
"""

WORKING = f"""\
✻ Cogitating… (12s · esc to interrupt)

{"─" * 40} Cv-UI ─
❯ 
{RULE}
  \U0001f4e6/My Projects/Cloude Code Repos/Dev/cloudecode | Opus 5.5 | 12%
  ⏵⏵ bypass permissions on (shift+tab to cycle)
  ⏸ some-task               paused · waiting for input
"""


def test_the_argent_countdown_footer_is_a_stop() -> None:
    assert limit_detect.pane_stop_label(ARGENT_COUNTDOWN) == "1am"


def test_paused_background_rows_are_a_stop() -> None:
    assert limit_detect.pane_stop_label(CV_UI_PAUSED) == "1am"


def test_prose_in_the_scrollback_is_not_a_stop() -> None:
    assert limit_detect.pane_stop_label(PROSE_ONLY) is None


def test_a_working_session_is_not_a_stop() -> None:
    assert limit_detect.pane_stop_label(WORKING) is None
    assert limit_detect.pane_stop_label("") is None
    assert limit_detect.pane_stop_label(None) is None


def test_the_countdown_line_alone_is_not_enough() -> None:
    assert limit_detect.pane_stop_label(ARGENT_COUNTDOWN.replace("Continuing automatically", "Carrying on")) is None


def _evidence(screen: str) -> auto_restart.SessionEvidence:
    manager = SimpleNamespace(tmux_socket_name=lambda: "cloude", claude_uuid_for_tmux_name=lambda name: "conv-1")
    evidence = auto_restart.SessionEvidence(manager)

    async def no_transcript_stop(info):
        return None

    evidence._transcript_stop = no_transcript_stop  # type: ignore[method-assign]
    return evidence


def test_evidence_turns_a_footer_stop_into_a_pane_record(monkeypatch) -> None:
    monkeypatch.setattr(auto_restart, "capture_screen", lambda socket, name: ARGENT_COUNTDOWN)
    info = SimpleNamespace(tmux_session="carnivore_Cobalt-2")
    stop = asyncio.run(_evidence(ARGENT_COUNTDOWN).limit_stop(info))
    assert limit_detect.is_pane_stop(stop)
    assert stop.uuid.startswith("pane:conv-1:1am:") and stop.resets_at is None and stop.timestamp is not None


def test_evidence_finds_nothing_on_prose(monkeypatch) -> None:
    monkeypatch.setattr(auto_restart, "capture_screen", lambda socket, name: PROSE_ONLY)
    assert asyncio.run(_evidence(PROSE_ONLY).limit_stop(SimpleNamespace(tmux_session="carnivore_cloudecode-2"))) is None


def test_an_open_shell_vetoes_only_without_the_footer_proof() -> None:
    shell = SimpleNamespace(activity_status="working_subagent", activity_hint="shell")
    pane = SimpleNamespace(uuid="pane:c:1am:2026-10-22")
    record = SimpleNamespace(uuid="abc")
    assert auto_restart._restartable(shell, pane)
    assert not auto_restart._restartable(shell, record)
    assert not auto_restart._restartable(shell, None)
    assert not auto_restart._restartable(SimpleNamespace(activity_status="dead", activity_hint=None), pane)
    assert auto_restart._restartable(SimpleNamespace(activity_status="working", activity_hint=None), record)
