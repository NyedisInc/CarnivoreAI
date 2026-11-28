
from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.plugin_studio import store
from src.core.plugin_studio.errors import WorkspaceConflictError, WorkspaceValidationError
from src.plugins.cli import templates

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_STUDIO_ID_RE = re.compile(r"^stu_[a-f0-9]{10}$")


def derive_plugin_id(name: Optional[str], prompt: str) -> str:
    if name is not None and name.strip():
        candidate = name.strip()
        prob = templates.name_problem(candidate)
        if prob:
            raise WorkspaceValidationError(prob, code="invalid_plugin_id")
        return candidate

    words = [w for w in _NON_ALNUM_RE.split((prompt or "").lower()) if w]
    stem = "".join(words)[:16]
    if not stem or not stem[0].isalpha():
        stem = f"plug{stem}"[:16]
    if len(stem) < 4:
        stem = f"{stem}plug"[:12]

    if not templates.name_problem(stem):
        return stem

    suffix = uuid.uuid4().hex[:4]
    candidate = f"{stem[:18]}{suffix}"
    if not templates.name_problem(candidate):
        return candidate
    return f"plug{uuid.uuid4().hex[:8]}"


def _build_studio_brief(
    *,
    studio_id: str,
    plugin_id: str,
    template: str,
    prompt: str,
    files: Dict[str, str],
) -> str:
    file_list = "\n".join(f"- `{rel}`" for rel in sorted(files))
    return (
        f"# Plugin Studio Brief — `{plugin_id}`\n\n"
        f"- **Studio ID**: `{studio_id}`\n"
        f"- **Plugin ID**: `{plugin_id}`\n"
        f"- **Template / Runtime**: `{template}`\n\n"
        "## User Goal\n\n"
        f"{prompt.strip()}\n\n"
        "## Manifest v2 (`carnivore.toml`) Summary\n\n"
        "- `schema = 2` and `api_version = 1` are required.\n"
        "- Declare all host permissions under `[permissions]` with plain-English explanations in `[permissions.reasons]`.\n"
        "- Declare tools under `[[mcp.tools]]`, declarative UI / routes under `[ui]`, and keep `license = \"MIT\"` matching `LICENSE.md`.\n"
        "- Never hardcode secrets or use dynamic/obfuscated execution (`eval`, undeclared network calls, `shell=True`).\n\n"
        "## Generated Workspace Files\n\n"
        f"{file_list}\n"
        "- `STUDIO_BRIEF.md`\n\n"
        "## Live Development Workflow\n\n"
        "1. Keep `carnivore plugin dev` (or Studio Dev Mode) active while editing files in this workspace for `<300ms` hot reload.\n"
        "2. Run Warez Readiness checks and `[Test in Sandbox]` before installing or publishing.\n"
        "3. For UI surfaces, return valid Declarative UI `schema = 1` documents from `ui.render` or `[ui.widget]`/`[ui.views]`.\n"
    )


def create_workspace(
    state_dir: Path,
    *,
    prompt: str,
    template: str = templates.DEFAULT_TEMPLATE,
    name: Optional[str] = None,
    agent_kind: str = "claude",
    author: str = templates.DEFAULT_AUTHOR,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        raise WorkspaceValidationError("prompt must be non-empty", code="prompt_required")
    if template not in templates.TEMPLATES:
        raise WorkspaceValidationError(
            f"template must be one of {', '.join(templates.TEMPLATES)}",
            code="invalid_template",
        )
    plugin_id = derive_plugin_id(name, clean_prompt)

    base_dir = store.workspaces_dir(state_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    root_real = Path(os.path.realpath(base_dir))

    studio_id = f"stu_{uuid.uuid4().hex[:10]}"
    if not _STUDIO_ID_RE.match(studio_id):
        raise WorkspaceValidationError("failed to allocate valid studio id", code="invalid_studio_id")
    dest = root_real / studio_id
    if not dest.resolve().is_relative_to(root_real) or dest.resolve() == root_real:
        raise WorkspaceValidationError("workspace path escaped studio root", code="studio_workspace_escape")
    if dest.exists():
        raise WorkspaceConflictError(f"workspace {studio_id} already exists", code="studio_workspace_exists")

    try:
        files = templates.scaffold(dest, plugin_id, template=template, author=author)
    except templates.TemplateError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise WorkspaceValidationError(str(exc), code="template_scaffold_failed") from exc

    brief_text = _build_studio_brief(
        studio_id=studio_id,
        plugin_id=plugin_id,
        template=template,
        prompt=clean_prompt,
        files=files,
    )
    (dest / "STUDIO_BRIEF.md").write_text(brief_text, encoding="utf-8")

    now = store.utc_now_iso()
    record: Dict[str, Any] = {
        "studio_id": studio_id,
        "plugin_id": plugin_id,
        "name": plugin_id,
        "template": template,
        "prompt": clean_prompt,
        "agent_kind": agent_kind,
        "folder": os.path.realpath(dest),
        "session_id": None,
        "session_tmux": None,
        "dev_active": False,
        "created_at": now,
        "updated_at": now,
        "last_readiness": None,
    }
    saved = store.upsert_workspace(state_dir, record)
    file_entries = store.list_workspace_files(dest)
    return saved, file_entries


def delete_workspace_dir(state_dir: Path, record: Dict[str, Any]) -> None:
    raw_folder = str(record.get("folder") or "")
    if not raw_folder:
        return
    base_real = Path(os.path.realpath(store.workspaces_dir(state_dir)))
    target = Path(raw_folder)
    if not target.exists() or target.is_symlink():
        return
    target_real = Path(os.path.realpath(target))
    if target_real.is_relative_to(base_real) and target_real != base_real:
        shutil.rmtree(target_real, ignore_errors=True)
