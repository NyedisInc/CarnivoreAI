
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from tests.blueprints_helpers import member, spec

# ruff: noqa: E402
from src.core import blueprints_shape
from src.core.blueprints_store import BlueprintSecret, serialize
from src.models.blueprints import (
    OPENING_PROMPT_MAX_BYTES, SESSIONS_MAX, SKILLS_PER_SESSION_MAX, BlueprintSpec,
    LaunchRequest,
)
from src.models.session_requests import CreateSessionRequest


def _ok(**extra):
    return spec("team", member("api", "/tmp/a", **extra), member("web", "/tmp/b"))


def _refused(document) -> str:
    with pytest.raises(ValidationError) as caught:
        BlueprintSpec.model_validate(document)
    return str(caught.value)


def test_a_minimal_spec_validates_and_defaults_version_one():
    parsed = BlueprintSpec.model_validate(_ok())
    assert parsed.version == 1 and [s.label for s in parsed.sessions] == ["api", "web"]


@pytest.mark.parametrize("where", ["top", "session", "folder"])
def test_an_unknown_field_is_refused_at_every_level(where):
    document = _ok()
    target = {"top": document, "session": document["sessions"][0],
              "folder": document["sessions"][0]["folder"]}[where]
    target["api_key"] = "x"
    assert "api_key" in _refused(document)


def test_caps_on_sessions_skills_prompt_and_name():
    many = spec("t", *[member(f"s{i}", "/tmp") for i in range(SESSIONS_MAX + 1)])
    _refused(many)
    skills = [f"alex/s{i}" for i in range(SKILLS_PER_SESSION_MAX + 1)]
    _refused(_ok(skills=skills))
    _refused(_ok(opening_prompt="a " * (OPENING_PROMPT_MAX_BYTES // 2 + 1)))
    _refused(spec("n" * 61, member("a", "/tmp")))
    _refused(spec("t"))


def test_the_model_guard_is_the_create_routes_own():
    assert "model" in _refused(_ok(model="x; rm -rf /"))
    assert BlueprintSpec.model_validate(_ok(model="anthropic/claude-opus-4")).sessions[0].model


@pytest.mark.parametrize("prompt", ["--dangerously-skip-permissions", "update", "a\x00b"])
def test_an_opening_prompt_the_cli_would_misread_is_refused(prompt):
    _refused(_ok(opening_prompt=prompt))
    with pytest.raises(ValidationError):
        CreateSessionRequest(opening_prompt=prompt)


def test_a_prompt_on_a_shell_member_is_refused():
    _refused(_ok(family="shell", opening_prompt="list the files please"))


def test_labels_are_unique_ignoring_case_and_catalog_ids_are_checked():
    _refused(spec("t", member("API", "/a"), member("api", "/b")))
    _refused(_ok(skills=["../../etc"]))
    _refused(_ok(skills=["alex/sme", "alex/sme"]))


@pytest.mark.parametrize("branch", ["--upload-pack=touch /tmp/x", "a b", "x;y", "$(id)"])
def test_a_hostile_branch_name_is_refused_by_the_model(branch):
    document = spec("t", {"label": "w", "family": "claude", "folder": {
        "mode": "worktree", "repo_path": "/r", "base_branch": "master", "branch": branch}})
    _refused(document)


def test_the_shape_template_names_members_only():
    good = blueprints_shape.default_shape([1, 2])
    template = blueprints_shape.template_from_layout(good, [1, 2])
    assert BlueprintSpec.model_validate({**_ok(), "shape_template": template}).shape_template
    _refused({**_ok(), "shape_template": good})
    beyond = copy.deepcopy(template)
    beyond["layout"]["rows"][0]["slots"][1]["id"] = "terminal:member:5"
    _refused({**_ok(), "shape_template": beyond})


def test_materialize_drops_a_member_that_did_not_launch_and_adds_an_unshown_one():
    template = blueprints_shape.template_from_layout(blueprints_shape.default_shape([1, 2]), [1, 2])
    shape = blueprints_shape.materialize(template, {0: 41, 2: 43}, 3)
    from src.core.layouts.shape import member_row_ids, validate

    assert member_row_ids(validate(shape)) == [41, 43]


def test_a_secret_in_a_spec_is_refused_by_name_not_value():
    key = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    parsed = BlueprintSpec.model_validate(_ok(opening_prompt=f"use token {key} for the api"))
    with pytest.raises(BlueprintSecret) as caught:
        serialize(parsed)
    assert key not in str(caught.value) and caught.value.detectors


def test_launch_request_members_are_distinct_indices():
    with pytest.raises(ValidationError):
        LaunchRequest(members=[0, 0])
    with pytest.raises(ValidationError):
        LaunchRequest(members=[-1])
    assert LaunchRequest(members=[2, 0]).members == [0, 2]


def test_a_paired_mac_host_key_is_not_read_as_a_credential():
    key = "peer-" + "4d3f86db" + "ba6b26ba70c9"
    assert key in serialize(BlueprintSpec.model_validate(_ok(host_key=key)))
