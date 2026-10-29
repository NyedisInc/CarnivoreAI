
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import restore_offer_routes as routes
from src.core.attention.pane_markers import RESTING_PROMPT_MARKER
from src.core.attention.pane_prompt_box import input_box_drawn
from src.core.attention.registry_record import parse_registry_record
from src.core.session_restore_startup_check import watch_for_startup_prompts

RULE = "─" * 60

TRUST_DIALOG = "\n".join([
    RULE,
    " Accessing workspace:",
    " /private/tmp/untrusted",
    " Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source",
    " Claude Code'll be able to read, edit, and execute files here.",
    " Security guide",
    " ❯ No, exit",
    "   Yes, I trust this folder",
    " Enter to confirm · Esc to cancel",
])

CHROME_DIALOG = "\n".join([
    RULE,
    "  Claude in Chrome extension detected",
    "  ❯ No, keep browser tools off",
    "    Yes, use my browser",
    "  Enter to confirm · Esc to keep browser tools off",
])

INPUT_BOX = "\n".join(["✻ Welcome back", "", RULE, "❯ ", RULE, "  ? for shortcuts"])


class _Clock:

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _watch(tails, *, fresh=(), since=None, registry=None, clock=None):
    clock = clock or _Clock()
    reads = []

    def capture(*, socket, name, lines):
        reads.append(name)
        seq = tails[name]
        return seq[min(reads.count(name), len(seq)) - 1]

    got = watch_for_startup_prompts(
        list(tails), socket="s", fresh=fresh, since=since, window=5.0, interval=0.75,
        capture=capture, registry_index=lambda: registry or {},
        clock=clock.now, sleep=clock.sleep,
    )
    return got, reads, clock


def test_the_captured_dialogs_are_not_an_input_box() -> None:
    assert input_box_drawn(INPUT_BOX.splitlines(), RESTING_PROMPT_MARKER) is True
    assert input_box_drawn(TRUST_DIALOG.splitlines(), RESTING_PROMPT_MARKER) is False
    assert input_box_drawn(CHROME_DIALOG.splitlines(), RESTING_PROMPT_MARKER) is False


def test_a_fresh_pane_past_startup_ends_the_watch_at_once() -> None:
    got, reads, clock = _watch({"a": [INPUT_BOX]}, fresh=["a"])
    assert got == {"a": False}
    assert reads == ["a"] and clock.t == 0.0


def test_a_pane_still_booting_is_watched_until_its_box_draws() -> None:
    got, reads, clock = _watch({"a": ["", "", INPUT_BOX]}, fresh=["a"])
    assert got == {"a": False}
    assert reads == ["a", "a", "a"] and clock.t == 1.5


def test_a_husk_is_never_ended_by_a_stale_input_box() -> None:
    got, reads, clock = _watch({"h": [INPUT_BOX]}, fresh=[])
    assert got == {"h": False}
    assert len(reads) > 1 and clock.t > 4.0, "the husk was dropped on stale evidence"


def test_the_trust_prompt_is_still_reported() -> None:
    got, _reads, _clock = _watch(
        {"t": ["", TRUST_DIALOG], "c": [CHROME_DIALOG], "a": [INPUT_BOX]},
        fresh=["t", "c", "a"],
    )
    assert got == {"t": True, "c": True, "a": False}


def _record(name: str, started_ms: int):
    return parse_registry_record(
        {"pid": os.getpid(), "status": "idle", "tmux": f"{name}:@1.%1",
         "startedAt": started_ms, "sessionId": "c-1"},
        path_pid=os.getpid(),
    )


def test_a_registered_claude_ends_the_watch_even_for_a_husk() -> None:
    since = time.time()
    fresh_record = {"h": _record("h", int((since + 1) * 1000))}
    got, reads, clock = _watch({"h": [INPUT_BOX]}, since=since, registry=fresh_record)
    assert got == {"h": False} and reads == ["h"] and clock.t == 0.0


def test_a_registry_record_from_before_the_reopen_is_ignored() -> None:
    since = time.time()
    old_record = {"h": _record("h", int((since - 60) * 1000))}
    _got, reads, clock = _watch({"h": [INPUT_BOX]}, since=since, registry=old_record)
    assert len(reads) > 1 and clock.t > 4.0


def test_reopens_run_concurrently_capped_and_in_order(monkeypatch) -> None:
    live = {"now": 0, "peak": 0}
    by_name: dict = {}

    async def fake_reopen_one(manager, item, agent_type):
        name = item["tmux_name"]
        assert not by_name.get(name), f"two creates of {name} overlapped"
        by_name[name] = True
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        by_name[name] = False
        return {"session_uuid": item["session_uuid"], "outcome": "reopened"}

    monkeypatch.setattr(routes, "_reopen_one", fake_reopen_one)
    jobs = [({"session_uuid": f"u{i}", "tmux_name": f"n{i}"}, "claude") for i in range(10)]
    jobs.insert(1, ({"session_uuid": "dup", "tmux_name": "n0"}, "claude"))

    started = time.monotonic()
    out = asyncio.run(routes._reopen_all(object(), jobs))
    elapsed = time.monotonic() - started

    assert [r["session_uuid"] for r in out] == [j[0]["session_uuid"] for j in jobs]
    assert live["peak"] == routes.REOPEN_CONCURRENCY
    assert elapsed < 0.05 * len(jobs) * 0.6, "the reopens did not overlap"
