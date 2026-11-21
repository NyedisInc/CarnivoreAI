
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.config import settings
from src.core.approvals.extract import extract_dialog
from tests.python.approvals.auto_helpers import make_engine
from tests.python.approvals.test_auto_answer_rules import AWAITING, Presses, reading

SCREEN = """
────────────────────────────────────────────────────────────────────────────────
 Adding a new directory:

 {path}

 This session hasn't worked here before. Is this a directory you created or one you trust?

 Claude Code'll be able to read, edit, and execute files here. Its skills, commands, and agents load and can run commands, and so
 can the git settings of its repository. Your answer holds for this session. Starting Claude Code in this directory and trusting it
 there lasts, and covers its whole repository or everything below it.

 Security guide

 ❯ No, exit
   Yes, add it

 Enter to confirm · Esc to cancel
"""


def test_only_a_real_swarm_desk_folder_is_added(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "Application Support" / "Carnivore"
    (state / "swarm" / "desk" / "75").mkdir(parents=True)
    (state / "swarm" / "desk" / "notes").mkdir()
    (state / "swarm" / "other").mkdir()
    (tmp_path / "outside").mkdir()
    (state / "swarm" / "desk" / "76").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    work = str(tmp_path / "proj")

    def pressed(path: Path) -> list:
        presses = Presses()

        async def info(_sid: str):
            return SimpleNamespace(session=SimpleNamespace(id=_sid, working_dir=work), agent_family="claude", startup_gate=AWAITING, tmux_session="t")

        dialog = extract_dialog(SCREEN.format(path=path), "claude")
        assert dialog is not None and dialog.startup_kind == "trust"
        engine = make_engine(answer=presses, info=info)

        async def go() -> None:
            for _ in range(2):
                task = engine.on_observation(SimpleNamespace(session_id="ses_1"), reading(dialog))
                if task is not None:
                    await task

        asyncio.run(go())
        return presses.labels

    desk = state / "swarm" / "desk"
    assert pressed(desk / "75") == ["Yes, add it"]
    assert pressed(desk / "notes") == []
    assert pressed(desk / "76") == []
    assert pressed(state / "swarm" / "other") == []
    assert pressed(tmp_path / "outside") == []
