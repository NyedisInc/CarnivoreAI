
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.api import recreate_action, recreate_routes as rr
from src.core.session_imported_restart import DIRECTORY_NOT_FOUND, ResumeDirectory


def test_absent_in_profile_regathers_fresh(monkeypatch, tmp_path):
    calls = []

    def fake_gather(uuid, overrides, *, fresh=False, corpus_root=None):
        calls.append((fresh, corpus_root))
        directory = ResumeDirectory(outcome=DIRECTORY_NOT_FOUND) if not fresh else ResumeDirectory(outcome="unchecked")
        raise_stop = {"row": {"session_uuid": uuid, "working_dir": "/w"}, "name": "n", "presence": SimpleNamespace(outcome="gone"),
                      "extra_args": None, "directory": directory}
        return raise_stop

    async def gate(_wd):
        return None

    monkeypatch.setattr(rr, "_gather", fake_gather)
    monkeypatch.setattr(recreate_action.project_home, "require_active", gate)
    monkeypatch.setattr(rr, "validate_agent_choice", lambda *a, **k: (_ for _ in ()).throw(StopIteration))
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path)}
    try:
        asyncio.run(recreate_action.recreate_by_uuid("u1", "claude", get_manager=lambda: None, extra_env=env,
                                                     fresh_if_transcript_absent=True))
    except (StopIteration, RuntimeError):
        pass
    assert calls == [(False, tmp_path / "projects"), (True, tmp_path / "projects")]
