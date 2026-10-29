
from __future__ import annotations

import json
from pathlib import Path

from src.core.launch_profiles import installed
from src.core.launch_wrappers.family_defaults import ensure_family_defaults
from tests.python.launch_profiles.test_launch_profiles_routes import env  # noqa: F401

EXAMPLES = Path(__file__).resolve().parents[3] / "web/src/lib/launch-profiles-page/example-profiles.json"


def _by_id(body: dict) -> dict:
    return {p["id"]: p for p in body["profiles"]}


def test_family_binary_reads_the_program_not_the_wrapper_words():
    assert installed.family_binary("claude") == "claude"
    assert installed.family_binary("codex") == "codex"
    assert installed.family_binary("openclaw") == "openclaw"
    assert installed.family_binary("nonsense") is None


def test_shell_and_custom_are_always_installed_others_follow_the_locator():
    nothing = lambda _name: None  # noqa: E731
    assert installed.harness_installed("shell", nothing) is True
    assert installed.harness_installed("custom", nothing) is True
    assert installed.harness_installed("claude", nothing) is False
    assert installed.harness_installed("codex", lambda n: f"/bin/{n}") is True


def test_list_reports_installed_per_profile_and_keeps_every_profile(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(installed, "_locate", lambda name: "/bin/claude" if name == "claude" else None)
    monkeypatch.setattr("src.api.launch_profiles_routes.harness_installed",
                        lambda h: installed.harness_installed(h, installed._locate))
    body = env.client.get("/api/v1/launch-profiles").json()
    rows = _by_id(body)
    assert rows["claude-main"]["installed"] is True
    assert rows["codex-yolo"]["installed"] is False
    assert len(body["profiles"]) == 4


def test_hidden_defaults_are_still_seeded():
    seeded = ensure_family_defaults([])
    assert {w["family"] for w in seeded} >= {"claude", "codex"}


def test_every_example_is_a_profile_the_validator_accepts():
    from src.config.launch_profiles import LaunchProfile
    for ex in json.loads(EXAMPLES.read_text()):
        LaunchProfile.model_validate({
            "id": ex["id"].replace("_", "-"), "harness": ex["harness"], "label": ex["id"], "model": ex["model"],
            "permissions": ex["permissions"], "flags": ex["flags"],
        })
