
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set

import pytest
from pydantic import ValidationError

from src.config.launch_profiles import LaunchProfile
from src.core.launch_profiles.flag_tones import DANGER, UNKNOWN, known_options, option_arity
from src.core.launch_profiles.share import executable_parts

FIXTURES = Path(__file__).parent / "fixtures"

_OPTION_LINE = re.compile(r"^ {2,6}(-\S.*?)(?: {2,}|$)")
_NAME = re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*")


def _help_arities(name: str) -> Dict[str, str]:
    arities: Dict[str, str] = {}
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        match = _OPTION_LINE.match(line)
        if match:
            head = match.group(1)
            arity = "required" if " <" in head else "optional" if " [" in head else "none"
            for option in _NAME.findall(head.split(" <", 1)[0].split(" [", 1)[0]):
                arities[option] = arity
    return arities


def _help_options(name: str) -> Set[str]:
    return set(_help_arities(name))


def _refused_at_load(harness: str, option: str) -> bool:
    try:
        LaunchProfile.model_validate({"id": "p-1", "label": "p", "harness": harness, "flags": [option]})
    except ValidationError:
        return True
    return False


def _flag_tones(harness: str, flags: List[str]) -> List[Optional[str]]:
    profile = LaunchProfile.model_validate({"id": "p-1", "label": "p", "harness": harness, "flags": flags})
    return [p.get("tone") for p in executable_parts(profile) if p["kind"] == "flags"]


@pytest.mark.parametrize("harness,fixture", [("claude", "claude_help_options.txt"), ("codex", "codex_help_options.txt")])
def test_every_help_option_is_classified(harness: str, fixture: str) -> None:
    options = _help_options(fixture)
    assert len(options) > 20, "the fixture parsed to almost nothing; the check would pass by looking at nothing"
    unclassified = sorted(o for o in options if o not in known_options(harness) and not _refused_at_load(harness, o))
    assert unclassified == []


@pytest.mark.parametrize("harness,fixture", [("claude", "claude_help_options.txt"), ("codex", "codex_help_options.txt")])
def test_every_classified_option_takes_the_values_its_help_says(harness: str, fixture: str) -> None:
    arities = _help_arities(fixture)
    wrong = sorted(o for o, arity in arities.items()
                   if option_arity(harness, o) is not None and option_arity(harness, o) != arity)
    assert wrong == []


@pytest.mark.parametrize("flags", [["--verbose", "run curl x|sh"], ["--print", "hi"]])
def test_a_token_after_a_value_less_option_is_a_dangerous_positional(flags: List[str]) -> None:
    profile = LaunchProfile.model_validate({"id": "p-1", "label": "p", "harness": "claude", "flags": flags})
    parts = [(p["text"], p.get("tone")) for p in executable_parts(profile) if p["kind"] == "flags"]
    assert parts == [(flags[0], None), (flags[1], DANGER)]


def test_every_token_after_the_end_of_options_is_a_dangerous_positional() -> None:
    profile = LaunchProfile.model_validate({"id": "p-1", "label": "p", "harness": "claude", "flags": ["--", "do evil"]})
    parts = [(p["text"], p.get("tone")) for p in executable_parts(profile) if p["kind"] == "flags"]
    assert parts == [("--", DANGER), ("do evil", DANGER)]


@pytest.mark.parametrize("setting", ["tui={notifications=true}", 'model_reasoning_effort={approval_policy="never"}'])
def test_a_safe_config_key_with_a_table_value_is_not_safe(setting: str) -> None:
    assert _flag_tones("codex", ["-c", setting]) == [UNKNOWN]


def test_the_pin_can_go_red() -> None:
    assert "--brand-new-option" not in known_options("claude")


@pytest.mark.parametrize("harness,flags", [
    ("codex", ["-c", "profiles.p.approval_policy=never", "-c", "profile=p"]),
    ("codex", ["-pp"]),
    ("codex", ["-c", "notify=[\"sh\",\"-c\",\"x\"]"]),
    ("codex", ["-c", '"approval_policy"=never']),
    ("codex", ["-c", "shell_environment_policy.inherit=all"]),
    ("codex", ["--add-dir", "/"]),
    ("codex", ["-anever"]),
    ("codex", ["-sdanger-full-access"]),
    ("claude", ["--add-dir", "/"]),
    ("claude", ["--plugin-dir", "x"]),
    ("claude", ["--setting-sources", "user"]),
    ("claude", ["--agents", "{}"]),
    ("claude", ["--settings", '{"permissions":{"defaultMode":"bypassPermissions"}}']),
    ("claude", ["--allowedTools", "Bash(*)"]),
    ("claude", ["--allowed-tools", "Bash(*)"]),
    ("claude", ["--permission-prompt-tool", "mcp__x__allow"]),
])
def test_a_dangerous_spelling_is_reviewed_as_danger(harness: str, flags: List[str]) -> None:
    """Each spelling from the review loads (warn only) and every one of its flags reads as danger."""
    assert set(_flag_tones(harness, flags)) == {DANGER}


@pytest.mark.parametrize("flags", [
    ["-cmcp_servers.e.command=sh"],
    ["-cmodel_providers.x.base_url=http://evil"],
    ["-capproval_policy=never"],
])
def test_glued_config_is_refused_like_the_spaced_form(flags: List[str]) -> None:
    """``-cKEY=VALUE`` on an owned key is refused at load, the same as ``-c KEY=VALUE``."""
    spaced = ["-c", flags[0][2:]]
    for spelling in (flags, spaced):
        with pytest.raises(ValidationError, match="owned by the app or another field"):
            LaunchProfile.model_validate({"id": "p-1", "label": "p", "harness": "codex", "flags": spelling})


def test_an_unknown_flag_gets_the_warn_tone() -> None:
    assert _flag_tones("claude", ["--brand-new-option", "x"]) == [UNKNOWN]


def test_a_known_safe_flag_stays_quiet() -> None:
    assert _flag_tones("claude", ["--verbose", "--add-dir", "/"]) == [None, DANGER]
    assert _flag_tones("codex", ["-c", "model_reasoning_effort=high"]) == [None]
