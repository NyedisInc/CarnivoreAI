
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from src.core.swarm.slugs import slugify


@pytest.mark.asyncio
async def test_tmux_name_is_a_slug_and_label_stays_readable(tmp_path, monkeypatch):
    from src.cplugs.host import session_actions

    seen = {}

    async def fake_create(request, body):
        seen["body"] = body
        return SimpleNamespace(id="ses_x")

    fake = ModuleType("src.api.session_crud_routes")
    fake.create_session = fake_create
    monkeypatch.setitem(sys.modules, "src.api.session_crud_routes", fake)
    label = "widget draft: E2E probe"
    assert await session_actions.start_in_folder(object(), str(tmp_path), label, "Read BRIEF.md in this folder") == "ses_x"
    assert seen["body"].project_name == "widget-draft-e2e-probe"
    assert seen["body"].label == label
    from src.core.session_name_claim import base_name_for_project

    assert base_name_for_project(seen["body"].project_name) == "carnivore_widget-draft-e2e-probe"


def test_slug_has_no_spaces():
    assert " " not in slugify("widget draft: E2E probe")
