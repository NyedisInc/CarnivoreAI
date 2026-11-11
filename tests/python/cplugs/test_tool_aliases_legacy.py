
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cplugs.host import runtime
from src.cplugs.sdk import manifest as m
from src.core.mcp import aliases

SURFACES = SimpleNamespace(mcp_tools={"task_manager_board_public_links_remove": object()})
RAW = {"publicboard_links_remove": "task_manager_board_public_links_remove"}


def test_an_alias_named_for_a_folded_plugin_is_accepted() -> None:
    assert m._tool_aliases("reviewboard", RAW, SURFACES, legacy_ids=("publicboard",)) == RAW


def test_an_alias_named_for_nobody_it_absorbed_is_still_refused() -> None:
    with pytest.raises(m.ManifestError, match="must be named"):
        m._tool_aliases("reviewboard", RAW, SURFACES)
    with pytest.raises(m.ManifestError, match="must be named"):
        m._tool_aliases("reviewboard", RAW, SURFACES, legacy_ids=("nudge",))


def test_the_old_public_links_remove_name_still_means_the_new_one() -> None:
    if runtime.find("reviewboard") is None:
        pytest.skip("the review board is not shipped in this build (its folder was deleted)")
    assert runtime.find("reviewboard").manifest.mcp_tool_aliases == RAW
    assert aliases.canonical("publicboard_links_remove") == "task_manager_board_public_links_remove"
