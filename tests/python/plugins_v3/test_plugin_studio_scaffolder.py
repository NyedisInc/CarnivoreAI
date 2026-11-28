
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.core.plugin_studio import scaffolder, store
from src.core.plugin_studio.errors import StudioActionError, WorkspaceNotFoundError, WorkspaceValidationError
from src.plugins.cli import checker, templates


@pytest.mark.parametrize("template", templates.TEMPLATES)
def test_scaffolder_supports_all_7_templates_with_license_and_brief(tmp_path: Path, template: str) -> None:
    state_dir = tmp_path / "state"
    name = f"stu{template.replace('-', '')}"[:20]
    prompt = f"Build a helpful {template} plugin for developers."

    ws, files = scaffolder.create_workspace(
        state_dir,
        prompt=prompt,
        template=template,
        name=name,
        agent_kind="claude",
    )

    folder = Path(ws["folder"])
    assert ws["studio_id"].startswith("stu_")
    assert ws["plugin_id"] == name
    assert ws["template"] == template
    assert folder.is_dir()
    assert (folder / "carnivore.toml").is_file()
    assert (folder / "LICENSE.md").is_file()
    assert (folder / "STUDIO_BRIEF.md").is_file()

    brief = (folder / "STUDIO_BRIEF.md").read_text(encoding="utf-8")
    assert prompt in brief
    assert name in brief
    assert template in brief

    if template == "bash":
        assert os.access(folder / "run.sh", os.X_OK)

    rep = checker.check_folder(folder)
    assert rep.ok, rep.errors

    rel_paths = {f["path"] for f in files}
    assert {"carnivore.toml", "LICENSE.md", "STUDIO_BRIEF.md"} <= rel_paths


def test_scaffolder_validation_and_store_atomicity(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    with pytest.raises(WorkspaceValidationError) as exc_prompt:
        scaffolder.create_workspace(state_dir, prompt="   ", template="python")
    assert exc_prompt.value.code == "prompt_required"

    with pytest.raises(WorkspaceValidationError) as exc_tpl:
        scaffolder.create_workspace(state_dir, prompt="Build plugin", template="rust-wasm")
    assert exc_tpl.value.code == "invalid_template"

    with pytest.raises(WorkspaceValidationError) as exc_id:
        scaffolder.create_workspace(state_dir, prompt="Build plugin", template="python", name="flow")
    assert exc_id.value.code == "invalid_plugin_id"

    ws, _ = scaffolder.create_workspace(state_dir, prompt="Summarize session logs nicely", template="no-code")
    idx = store.index_path(state_dir)
    assert idx.is_file()
    assert stat.S_IMODE(idx.stat().st_mode) == 0o600

    assert len(store.list_workspaces(state_dir)) == 1
    fetched = store.get_workspace(state_dir, ws["studio_id"])
    assert fetched["plugin_id"] == ws["plugin_id"]

    updated = store.update_workspace(state_dir, ws["studio_id"], lambda r: {**r, "dev_active": True})
    assert updated["dev_active"] is True

    with pytest.raises(StudioActionError) as exc_esc:
        store.contained_workspace_folder(state_dir, str(tmp_path))
    assert exc_esc.value.code == "studio_workspace_escape"

    removed = store.remove_workspace(state_dir, ws["studio_id"])
    assert removed["studio_id"] == ws["studio_id"]
    scaffolder.delete_workspace_dir(state_dir, removed)
    assert not Path(ws["folder"]).exists()

    with pytest.raises(WorkspaceNotFoundError):
        store.get_workspace(state_dir, ws["studio_id"])
