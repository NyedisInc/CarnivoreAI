
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.restart_live_gate import nothing_running  # noqa: E402


def _manager(status="idle", hint=None, bg=0, subs=0, timers=0, evidence="clean", listed=True):
    info = NS(activity_status=status, activity_hint=hint, background_open=bg, subagents_running=subs, timers_live=timers)
    backend = NS(tmux_session="carnivore_a")
    if evidence == "clean":
        ev = NS(agent_family="claude", timers=NS(state="ok", live=0), subagents=NS(state="ok", running=0),
                background_process=NS(state="none", count=0), background_open=0, parked_work=None)
    elif evidence == "bg":
        ev = NS(agent_family="claude", timers=NS(state="ok", live=0), subagents=NS(state="ok", running=0),
                background_process=NS(state="running", count=1), background_open=0, parked_work=None)
    else:
        ev = None

    async def get_info(sid):
        return info if listed else None

    async def fresh(sid):
        return ev

    return NS(_registry=NS(backends={"ses_1": backend}), get_session_info=get_info, _fresh_evidence=fresh)


def _run(**kw):
    return asyncio.run(nothing_running(_manager(**kw), "carnivore_a"))


def test_idle_with_nothing_open_needs_no_box():
    assert _run() is True
    assert _run(status="finished_unread") is True


def test_busy_or_background_work_keeps_the_box():
    assert _run(status="working") is False
    assert _run(status="question") is False
    assert _run(hint="shell") is False
    assert _run(bg=1) is False
    assert _run(subs=1) is False
    assert _run(timers=1) is False
    assert _run(evidence="bg") is False


def test_unknown_or_unmeasured_keeps_the_box():
    assert _run(status="unknown") is False
    assert _run(listed=False) is False
    assert _run(evidence="none") is False
    assert asyncio.run(nothing_running(_manager(), "carnivore_other")) is False
