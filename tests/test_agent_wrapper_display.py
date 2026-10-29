
import pytest

from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.agent_family_display import resolve_family_for_display
from src.core.agent_wrapper_display import (
    NO_WRAPPER,
    WrapperDisplay,
    resolve_wrapper_for_display,
)
from src.core.agent_wrappers import AgentWrapper


def _live_wrappers_as_dicts():
    return [
        {"id": "claude-skip-permissions", "label": "claude", "family": "claude"},
        {"id": "cld", "label": "cld (keychain-backed)", "family": "claude"},
        {"id": "cldor", "label": "cldor (openrouter, keychain-backed)", "family": "claude"},
        {"id": "cldl", "label": "cldl (lm studio)", "family": "local"},
        {"id": "claude-chrome", "label": "claude (chrome)", "family": "claude"},
    ]


def _live_wrappers_as_models():
    return [
        AgentWrapper(script="run", **w) for w in _live_wrappers_as_dicts()
    ]


CLAUDE_WRAPPER_IDS = (
    "claude-skip-permissions",
    "cld",
    "cldor",
    "claude-chrome",
)




@pytest.mark.parametrize("wrapper_id", CLAUDE_WRAPPER_IDS)
def test_every_configured_claude_wrapper_resolves_to_the_claude_family(wrapper_id):
    family, source = resolve_family_for_display(
        wrapper_id, _live_wrappers_as_models()
    )
    assert family is AGENT_FAMILY_BY_NAME["claude"]
    assert source == "wrapper"


def test_the_non_claude_wrapper_is_not_dragged_into_the_claude_family():
    family, source = resolve_family_for_display("cldl", _live_wrappers_as_models())
    assert family is AGENT_FAMILY_BY_NAME["local"]
    assert source == "wrapper"


def test_a_null_agent_type_stays_unknown_and_is_never_faked_as_claude():
    family, source = resolve_family_for_display(None, _live_wrappers_as_models())
    assert family is None
    assert source == "unknown"


def test_an_unconfigured_wrapper_id_stays_unknown():
    family, source = resolve_family_for_display(
        "claude-deleted", _live_wrappers_as_models()
    )
    assert family is None
    assert source == "unknown"




@pytest.mark.parametrize("wrappers", [
    _live_wrappers_as_dicts(),
    _live_wrappers_as_models(),
])
def test_a_configured_wrapper_id_resolves_to_its_configured_label(wrappers):
    got = resolve_wrapper_for_display("claude-chrome", wrappers)
    assert got == WrapperDisplay("claude-chrome", "claude (chrome)")


@pytest.mark.parametrize("wrapper_id,expected", [
    ("claude-skip-permissions", "claude"),
    ("cld", "cld (keychain-backed)"),
    ("cldor", "cldor (openrouter, keychain-backed)"),
    ("cldl", "cldl (lm studio)"),
    ("claude-chrome", "claude (chrome)"),
])
def test_every_live_wrapper_is_nameable(wrapper_id, expected):
    assert resolve_wrapper_for_display(
        wrapper_id, _live_wrappers_as_models()
    ).label == expected


def test_matching_is_case_insensitive_like_the_family_resolver():
    assert resolve_wrapper_for_display(
        "  Claude-Chrome  ", _live_wrappers_as_models()
    ).label == "claude (chrome)"


def test_a_blank_label_falls_back_to_the_id_rather_than_an_empty_pill():
    got = resolve_wrapper_for_display(
        "bare", [{"id": "bare", "label": "   ", "family": "claude"}]
    )
    assert got.label == "bare"




def test_a_null_agent_type_names_no_wrapper():
    assert resolve_wrapper_for_display(None, _live_wrappers_as_models()) is NO_WRAPPER


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_agent_type_names_no_wrapper(value):
    assert resolve_wrapper_for_display(value, _live_wrappers_as_models()) is NO_WRAPPER


def test_an_unconfigured_wrapper_id_names_no_wrapper():
    assert resolve_wrapper_for_display(
        "claude-deleted", _live_wrappers_as_models()
    ) is NO_WRAPPER


def test_an_empty_wrapper_list_names_no_wrapper():
    assert resolve_wrapper_for_display("claude-chrome", []) is NO_WRAPPER


def test_a_bare_family_name_names_no_wrapper():
    assert resolve_wrapper_for_display("shell", _live_wrappers_as_models()) is NO_WRAPPER


def test_a_fingerprinted_value_can_never_name_a_wrapper():
    assert resolve_wrapper_for_display(
        "claude-chrome", _live_wrappers_as_models(), from_fingerprint=True
    ) is NO_WRAPPER
