
from __future__ import annotations

from types import SimpleNamespace

from tests.python.federation.test_peer_forward import world  # noqa: F401

from src.config import settings
from src.config.launch_profiles import LaunchProfile
from src.core.federation import peer_links  # noqa: F401


def test_a_local_profile_id_is_sent_to_the_peer_as_its_family(world, monkeypatch) -> None:  # noqa: F811
    cld = LaunchProfile.model_validate({"id": "cld", "label": "cld", "harness": "claude"})
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: (cld,))
    world.client.answers[("POST", "/sessions")] = (201, {"id": "ses_owner1", "working_dir": "/w"})
    world.client.answers[("GET", "/sessions")] = (200, {"tmux_session": "cloude_new"})
    for sent, expected in (("cld", "claude"), ("codex", "codex"), ("nope", "nope")):
        world.client.calls.clear()
        world.http.post("/api/v1/sessions", json={"host_key": world.key, "working_dir": "/w", "agent_type": sent})
        assert world.client.calls[0][2]["agent_type"] == expected


def test_a_launcher_picked_from_the_far_list_is_sent_as_is_and_the_flag_is_not(world, monkeypatch) -> None:  # noqa: F811
    cld = LaunchProfile.model_validate({"id": "cld", "label": "cld", "harness": "claude"})
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: (cld,))
    world.client.answers[("POST", "/sessions")] = (201, {"id": "ses_owner1", "working_dir": "/w"})
    world.client.answers[("GET", "/sessions")] = (200, {"tmux_session": "cloude_new"})
    world.http.post("/api/v1/sessions", json={"host_key": world.key, "working_dir": "/w", "agent_type": "cld", "agent_type_is_far": True})
    assert world.client.calls[0][2]["agent_type"] == "cld"
    assert "agent_type_is_far" not in world.client.calls[0][2]
