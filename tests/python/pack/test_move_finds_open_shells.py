
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.api import pack_move_env
from src.core.background_work.measured import BackgroundMeasure, STATE_RUNNING
from src.core.pack.migrate import live_agents
from src.core.pack.move import turn
from src.core.subagents.tally import ABSENT
from src.models import SessionInfo
from src.models.sessions import Session

SES = "ses_16e3b824"


def test_the_moves_own_row_carries_the_open_shell_so_the_move_stops_it_itself() -> None:
    row = SessionInfo(session=Session(id=SES, working_dir="/tmp/bubblepop"), tmux_session="carnivore_Sandboxmacos-3", label="Tetra",
                      agent_family="claude", activity_status="idle", status_source="registry", activity_hint="shell", startup_gate="ready",
                      subagents_running=0)
    evidence = SimpleNamespace(background_open=1, background_process=BackgroundMeasure(STATE_RUNNING, 1, "1 tool shell running"),
                               registry=None, parked_work=None, transcript=None)
    observation = SimpleNamespace(stale=False, evidence=evidence)

    async def list_session_infos():
        return [row.model_copy()]

    manager = SimpleNamespace(list_session_infos=list_session_infos, _attention_watcher=SimpleNamespace(observation_for=lambda sid, now=None: observation))
    app_state = SimpleNamespace(session_manager=manager)
    hooks, project_find = pack_move_env.source_hooks(app_state), pack_move_env.live_hooks(app_state).session.find
    async def scenario() -> None:
        assert await live_agents.classify([live_agents.LiveAgent(SES, "Tetra")], project_find) == (1, [])
        await turn.wait_for_turn_end(lambda: project_find(SES), 5, settle=0.05, poll=0.01, name="Tetra", shells_ok=True)
        assert turn.shells_only(await hooks.find(SES)) == 1
        await turn.wait_for_turn_end(lambda: hooks.find(SES), 5, settle=0.05, poll=0.01, name="Tetra", shells_ok=True)

    asyncio.run(scenario())


def test_a_working_subagent_row_with_only_a_shell_ends_the_wait_through_the_real_find() -> None:
    row = SessionInfo(session=Session(id=SES, working_dir="/tmp/bubblepop"), tmux_session="carnivore_Sandboxmacos-3", label="Tetra",
                      agent_family="claude", activity_status="working_subagent", status_source="transcript", startup_gate="ready")
    evidence = SimpleNamespace(background_open=1, background_process=BackgroundMeasure(STATE_RUNNING, 1, "1 tool shell running"),
                               registry=None, parked_work=None, transcript=None, subagents=ABSENT)
    observation = SimpleNamespace(stale=False, evidence=evidence)

    async def list_session_infos():
        return [row.model_copy()]

    manager = SimpleNamespace(list_session_infos=list_session_infos, _attention_watcher=SimpleNamespace(observation_for=lambda sid, now=None: observation))
    hooks = pack_move_env.source_hooks(SimpleNamespace(session_manager=manager))

    async def scenario() -> None:
        found = await hooks.find(SES)
        assert (found.subagents_running, found.background_open) == (0, 1)
        assert turn.shells_only(found) == 1
        await turn.wait_for_turn_end(lambda: hooks.find(SES), 5, settle=0.05, poll=0.01, name="Tetra", shells_ok=True)

    asyncio.run(scenario())
