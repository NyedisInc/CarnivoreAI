
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.python.approvals.auto_helpers import make_engine
from src.core.approvals.extract import extract_dialog
from src.core.swarm.auto_trust import CARRIED_WAIT_SECONDS as WAIT
from tests.python.pack.test_trust_carry import _screen


def _run(tmp_path, readings):
    folder = str(tmp_path.resolve())
    state, sent = {"gate": None, "now": 0.0}, []

    async def answer(sid, fingerprint, label):
        sent.append(label)

    async def info(_sid):
        return SimpleNamespace(session=SimpleNamespace(working_dir=folder), agent_family="claude", startup_gate=state["gate"])

    dialog = extract_dialog(_screen(folder), "claude")

    async def go():
        ack = make_engine(answer=answer, info=info, lookup=lambda _f: "op", clock=lambda: state["now"])
        for identity, gate, now in readings:
            state["gate"], state["now"] = gate, now
            obs = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=dialog, identity=identity))
            task = ack.on_observation(SimpleNamespace(session_id="ses_1"), obs)
            if task is not None:
                await task

    asyncio.run(go())
    return len(sent)


def test_a_pid_filling_in_does_not_restart_the_window(tmp_path) -> None:
    unknown, awaiting = "unknown", "awaiting_startup_prompt"
    none_pid, with_pid = ("s", "n", 1, None), ("s", "n", 1, 9)
    assert _run(tmp_path, [(none_pid, unknown, 0), (with_pid, unknown, WAIT - 1), (with_pid, awaiting, WAIT + 1)]) == 0
    assert _run(tmp_path, [(none_pid, unknown, 0), (with_pid, unknown, WAIT - 1), (with_pid, awaiting, WAIT - 0.5)]) == 1


def test_a_different_pid_is_a_new_launch_with_its_own_window(tmp_path) -> None:
    unknown, awaiting = "unknown", "awaiting_startup_prompt"
    assert _run(tmp_path, [(("s", "n", 1, 9), unknown, 0), (("s", "n", 1, 10), unknown, WAIT - 1), (("s", "n", 1, 10), awaiting, WAIT + 1)]) == 1
