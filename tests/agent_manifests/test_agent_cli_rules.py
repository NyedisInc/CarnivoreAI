
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.agent_manifests import engine
from src.core.attention.evidence import (
    STATE_BUSY, STATE_NEEDS_USER, STATE_UNKNOWN, Evidence, TIER_PANE,
)
from src.core.attention.manifest_reader import ManifestReading, read_manifest
from src.core.attention.registry_index import registry_for_session
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_NO_RECORD, TranscriptFacts
from src.core.session_status import LIVENESS_LIVE

FIXTURES = Path(__file__).with_name("fixtures")
SHIPPED = {"amp", "copilot", "cursor", "droid", "gemini", "kilo", "opencode", "pi"}


def _manifest(cli: str) -> engine.Manifest:
    return next(m for m in engine.manifests() if m.id == cli)


def _screen(name: str) -> str:
    return (FIXTURES / ("%s.txt" % name)).read_text(encoding="utf-8")


def test_every_shipped_rule_file_loads_with_rules_and_a_version():
    loaded = {m.id: m for m in engine.manifests()}
    assert set(loaded) == SHIPPED
    assert all(m.rules and m.version for m in loaded.values())


@pytest.mark.parametrize("cli,fixture,state", [
    ("opencode", "opencode-working", "working"),
    ("opencode", "opencode-idle", None),
    ("opencode", "opencode-interrupted", None),
    ("copilot", "copilot-trust", "blocked"),
    ("gemini", "gemini-trust", "blocked"),
    ("cursor", "cursor-trust", "blocked"),
])
def test_live_screens_give_the_state_the_cli_was_in(cli, fixture, state):
    match = engine.evaluate(_manifest(cli), _screen(fixture))
    assert (match.state if match else None) == state


def test_the_process_table_names_the_cli_under_the_pane_and_nothing_outside_it():
    parents = {100: 1, 101: 100, 102: 101, 200: 1}
    commands = {100: "-zsh", 101: "zsh -ic gemini", 102: "node /h/.nvm/bin/gemini --yolo",
                200: "/h/.opencode/bin/opencode"}
    assert engine.identify(100, parents, commands).id == "gemini"
    assert engine.identify(999, parents, commands) is None
    assert engine.identify(None, parents, commands) is None


def test_a_nested_quantifier_and_a_newer_engine_file_are_refused():
    with pytest.raises(engine.RuleFileError):
        engine.compile_pattern("(a+)+$")
    newer = 'id = "x"\nmin_engine_version = %d\n' % (engine.ENGINE_VERSION + 1)
    assert engine.parse_manifest(newer) is None
    with pytest.raises(engine.RuleFileError):
        engine.parse_manifest('id = "x"\n[[rules]]\nid = "r"\nstate = "working"\nregion = "osc_title"\n')


def _evidence(reading):
    return Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family="custom",
        registry=registry_for_session(tmux_name="carnivore_x", index={}),
        transcript=TranscriptFacts(verdict=FACTS_NO_RECORD), pane=None,
        now=datetime(2026, 10, 30, tzinfo=timezone.utc), manifest=reading,
    )


def test_the_resolver_turns_a_reading_into_a_light_and_no_match_into_unknown():
    working = resolve_attention(_evidence(ManifestReading("opencode", "v", "working", "progress_bar_working")))
    assert (working.state, working.tier) == (STATE_BUSY, TIER_PANE)
    blocked = resolve_attention(_evidence(ManifestReading("opencode", "v", "blocked", "permission_required")))
    assert (blocked.state, blocked.reason) == (STATE_NEEDS_USER, "permission")
    assert resolve_attention(_evidence(ManifestReading("opencode", "v"))).state == STATE_UNKNOWN


def test_the_screen_is_captured_only_when_a_known_cli_runs():
    calls = []
    snap = type("Snap", (), {"parents": {5: 4}, "commands": {5: "vim notes.md"}})()
    assert read_manifest(4, snap, lambda: calls.append(1) or "") is None
    assert calls == []
    snap.commands = {5: "/h/bin/opencode"}
    assert read_manifest(4, snap, lambda: _screen("opencode-working")).state == "working"


def test_a_hostile_screen_stays_cheap_across_every_rule_file():
    hostile = "\n".join(("opencode " * 60 + "esc a" + "⠀" * 40 + " " * 200)[:900] for _ in range(200))
    start = time.perf_counter()
    for manifest in engine.manifests():
        engine.evaluate(manifest, hostile)
    assert time.perf_counter() - start < 0.25


def test_an_osc_3008_status_code_flips_the_light_without_a_screen_capture():
    from src.core.session_output.escape_notices import TerminalNotices
    from src.core.session_output.escape_scanner import EscapeScanner

    notices = TerminalNotices()
    scanner_events = EscapeScanner().feed(b"out\x1b]3008;event=busy\x07more\x1b]3008;event=bogus\x1b\\")
    assert [(e.kind, e.title) for e in scanner_events] == [("status", "busy")]
    notices._queue.extend(("ses_s", e) for e in scanner_events)
    notices.drain()
    assert notices.status_for("ses_s") == "busy"
    calls = []
    snap = type("Snap", (), {"parents": {5: 4}, "commands": {5: "/h/bin/opencode"}})()
    reading = read_manifest(4, snap, lambda: calls.append(1) or _screen("opencode-working"), notices.status_for("ses_s"))
    assert calls == [] and reading.code == "busy"
    assert resolve_attention(_evidence(reading)).state == STATE_BUSY
    waiting = resolve_attention(_evidence(read_manifest(4, type("S", (), {"parents": {}, "commands": {}})(),
                                                         lambda: None, "waiting")))
    assert waiting.state == STATE_NEEDS_USER
    assert resolve_attention(_evidence(ManifestReading("program", "osc 3008", code="done"))).state != STATE_UNKNOWN
    notices.on_observation("ses_s", "dead", "custom")
    assert notices.status_for("ses_s") is None
