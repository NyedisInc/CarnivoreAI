
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.pack.relay import target_side
from src.core.pack.span import body_host
from src.core.swarm import body


def test_recreate_hands_the_relay_profile_to_the_recreate_action(monkeypatch, tmp_path):
    monkeypatch.setattr(target_side.Path, "home", classmethod(lambda cls: tmp_path))
    profile = target_side.relay_profile_dir("work", "iid-home")
    (tmp_path / ".carnivore" / "accounts" / target_side.relay_profile_name("work", "iid-home")).mkdir(parents=True)
    env = body_host._relay_env("work", "iid-home")
    assert env == {"CLAUDE_CONFIG_DIR": profile}
    seen = {}

    async def fake_recreate(uuid, agent_type, *, get_manager, fresh, extra_env=None, **_):
        seen["extra_env"] = extra_env
        return SimpleNamespace(status="started", session_id="ses_x", detail="")

    async def run_db(fn):
        return {"session_uuid": "u1", "agent_type": "claude"}

    async def info(sid):
        return SimpleNamespace(session_row_id=7, tmux_session="t", session=SimpleNamespace(working_dir="/w", tmux_created_epoch=1))

    monkeypatch.setattr("src.api.recreate_action.recreate_by_uuid", fake_recreate)
    monkeypatch.setattr(body, "run_db", run_db)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(get_session_info=info))))
    out = asyncio.run(body_host._recreate(request, tmp_path, 7, env))
    assert out["id"] == "ses_x" and seen["extra_env"] == env
