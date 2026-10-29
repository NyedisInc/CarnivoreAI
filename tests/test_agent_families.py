
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fam_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fam_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.agent_families import (
    AGENT_FAMILIES,
    AGENT_FAMILY_BY_NAME,
    AGENT_FAMILY_NAMES,
    DEFAULT_FAMILY,
    RESERVED_FAMILY_NAMES,
    get_family,
    is_valid_family,
    resolve_agent_type,
    wrappers_for_family,
)
from src.core.agent_wrappers import AgentWrapper


def _w(wid, family="claude", **kw):
    base = {"id": wid, "family": family, "label": wid, "script": f"{wid} run"}
    base.update(kw)
    return AgentWrapper(**base)



def test_every_family_carries_a_standard_wrapper_that_launches():
    ids = set()
    for family in AGENT_FAMILIES:
        wrapper = AgentWrapper(
            id=family.default_wrapper_id,
            family=family.name,
            label=family.default_label,
            script=family.default_script,
            accepts_model=family.default_accepts_model,
        )
        assert wrapper.script.strip(), family.name
        assert '"$@"' in family.default_script, family.name
        assert family.default_wrapper_id not in RESERVED_FAMILY_NAMES, family.name
        ids.add(family.default_wrapper_id)
    assert len(ids) == len(AGENT_FAMILIES)


def test_family_names_are_unique_and_nonempty():
    names = [f.name for f in AGENT_FAMILIES]
    assert len(names) == len(set(names))
    assert all(names)


def test_reserved_names_exclude_claude():
    assert "claude" not in RESERVED_FAMILY_NAMES
    assert RESERVED_FAMILY_NAMES == frozenset(
        {"codex", "hermes", "openclaw", "local", "shell"}
    )


def test_is_valid_family_and_get_family_fallback():
    assert is_valid_family("codex")
    assert not is_valid_family("nope")
    assert get_family("nope").name == DEFAULT_FAMILY
    assert get_family(None).name == DEFAULT_FAMILY
    assert get_family("shell").default_wrapper_id == "shell-default"



def test_bare_shell_resolves_to_the_shell_family_not_a_wrapper():
    family, explicit = resolve_agent_type("shell", [_w("cld"), _w("claude")])
    assert family.name == "shell"
    assert explicit is None


@pytest.mark.parametrize("name", sorted(RESERVED_FAMILY_NAMES))
def test_every_reserved_name_resolves_as_a_family(name):
    family, explicit = resolve_agent_type(name, [])
    assert family.name == name
    assert explicit is None


def test_a_wrapper_can_never_shadow_a_reserved_family_name():
    smuggled = AgentWrapper.model_construct(
        id="shell", family="claude", label="x", script="x", entry=None,
        description=None, default=True, accepts_model=False,
    )
    family, explicit = resolve_agent_type("shell", [smuggled])
    assert family.name == "shell"
    assert explicit is None


def test_wrapper_id_wins_for_a_non_reserved_name():
    cld = _w("cld")
    family, explicit = resolve_agent_type("cld", [_w("claude"), cld])
    assert family.name == "claude"
    assert explicit is cld


def test_agent_type_claude_prefers_a_wrapper_literally_named_claude():
    seeded = _w("claude", default=False)
    other = _w("cld", default=True)
    family, explicit = resolve_agent_type("claude", [seeded, other])
    assert explicit is seeded


def test_agent_type_claude_falls_through_when_no_such_wrapper_id():
    family, explicit = resolve_agent_type("claude", [_w("cld", default=True)])
    assert family.name == "claude"
    assert explicit is None


@pytest.mark.parametrize("value", [None, "", "totally-unknown"])
def test_unknown_or_missing_agent_type_is_the_claude_family(value):
    family, explicit = resolve_agent_type(value, [])
    assert family.name == DEFAULT_FAMILY
    assert explicit is None


def test_resolution_is_case_insensitive():
    family, _ = resolve_agent_type("SHELL", [])
    assert family.name == "shell"


def test_a_codex_wrapper_id_resolves_into_the_codex_family():
    cw = _w("my-codex", family="codex")
    family, explicit = resolve_agent_type("my-codex", [_w("cld"), cw])
    assert family.name == "codex"
    assert explicit is cw



def test_wrappers_for_family_preserves_order_and_isolates_families():
    a, b, c = _w("a"), _w("b", family="codex"), _w("c")
    assert wrappers_for_family([a, b, c], "claude") == [a, c]
    assert wrappers_for_family([a, b, c], "codex") == [b]
    assert wrappers_for_family([a, b, c], "shell") == []


def test_wrappers_for_family_treats_a_familyless_dict_as_claude():
    legacy = {"id": "cld", "label": "cld", "script": "x"}
    assert wrappers_for_family([legacy], "claude") == [legacy]



def test_wrapper_family_defaults_to_claude_when_absent():
    w = AgentWrapper(id="cld", label="cld", script="cld")
    assert w.family == DEFAULT_FAMILY


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_wrapper_blank_family_coerces_to_default(blank):
    w = AgentWrapper(id="cld", label="cld", script="cld", family=blank)
    assert w.family == DEFAULT_FAMILY


@pytest.mark.parametrize("name", AGENT_FAMILY_NAMES)
def test_wrapper_accepts_every_registered_family(name):
    assert AgentWrapper(id="w", label="w", script="s", family=name).family == name


def test_wrapper_family_is_normalized_to_lowercase():
    assert AgentWrapper(id="w", label="w", script="s", family="CODEX").family == "codex"


def test_wrapper_rejects_an_unknown_family():
    with pytest.raises(ValueError):
        AgentWrapper(id="w", label="w", script="s", family="gpt")


def test_every_family_name_is_in_the_by_name_index():
    assert set(AGENT_FAMILY_BY_NAME) == set(AGENT_FAMILY_NAMES)




def test_the_alternate_screen_setting_is_read_at_launch(tmp_path):
    from src.config.agent_command import agent_command
    from src.config.agents import AgentsConfig

    values = iter([False, True])
    first = agent_command(
        "codex",
        agents=AgentsConfig(),
        resolve_state_dir=lambda: str(tmp_path),
        disable_alternate_screen=lambda: next(values),
    )
    second = agent_command(
        "codex",
        agents=AgentsConfig(),
        resolve_state_dir=lambda: str(tmp_path),
        disable_alternate_screen=lambda: next(values),
    )
    assert "--no-alt-screen" not in first
    assert "--no-alt-screen" in second
