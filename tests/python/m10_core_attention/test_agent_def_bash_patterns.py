
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.automations.targets.agent_def import AgentDef


def _def(tools: list, permission: str = "edits_in_folder") -> AgentDef:
    return AgentDef(folder="/tmp/x", prompt="go", tools=tools, permission=permission)


@pytest.mark.parametrize("pattern", ["Bash(*)", "Bash(* rm)", "Bash(:*)", "Bash(bash -c x)", "Bash(python3 *)",
                                     "Bash(/usr/bin/env x)", "Bash(sh:*)"])
def test_unconfined_patterns_refused(pattern: str) -> None:
    with pytest.raises(ValidationError):
        _def(["Read", pattern])


@pytest.mark.parametrize("pattern", ["Bash(git status)", "Bash(ls:*)", "Bash(npm test)"])
def test_scoped_patterns_allowed(pattern: str) -> None:
    assert _def(["Read", pattern]).tools[1] == pattern


def test_other_levels_unchanged() -> None:
    assert _def(["Bash(*)"], permission="unattended").tools == ["Bash(*)"]
