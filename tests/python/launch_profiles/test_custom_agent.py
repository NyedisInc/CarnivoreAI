
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.launch_profiles import LaunchProfile
from src.core.agent_wrapper_display import resolve_wrapper_for_display
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.launch_profiles.wrapper_view import wrappers_from_profiles


def _profile(**over) -> LaunchProfile:
    fields = {"id": "qwen", "harness": "custom", "label": "qwen code", "icon": "logo-qwen",
              "custom_command": {"script": 'qwen "$@"'}}
    return LaunchProfile.model_validate({**fields, **over})


def test_custom_agent_launches_its_command_and_degrades_a_requested_model(tmp_path: Path) -> None:
    plan = resolve_launch(LaunchRequest(profiles=(_profile(),), agent_type="qwen", explicit=True,
                                        model="some-model", model_is_explicit=True, scripts_dir=tmp_path))
    assert plan.display.harness == "custom"
    assert plan.script_file is not None and plan.script_file.content.strip() == 'qwen "$@"'
    assert "some-model" not in plan.command and plan.argv_tail == ()


def test_custom_agent_is_not_a_structured_profile() -> None:
    with pytest.raises(ValueError):
        LaunchProfile.model_validate({"id": "x", "harness": "custom", "label": "x"})
    with pytest.raises(ValueError):
        _profile(flags=["--foo"])


def test_session_row_carries_the_profile_icon() -> None:
    wrappers = wrappers_from_profiles([_profile()])
    shown = resolve_wrapper_for_display("qwen", wrappers)
    assert (shown.label, shown.icon) == ("qwen code", "logo-qwen")
