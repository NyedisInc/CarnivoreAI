from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.config_routes import user_scope_roots
from src.api.layouts_routes import layout_error, live_listing, run_on_store
from src.core.layouts import skill_suggestions as suggestions
from src.core.layouts import skill_translate as translate_mod
from src.core.account_switch.pane_account import read_pane_profile
from src.core.hosts.identity import is_remote_info
from src.core.layouts import store as store
from src.core.db import DatastoreUnreadableError
from src.models.layouts import SkillSuggestion, SkillSuggestionsResponse

router = APIRouter(prefix="/layouts", tags=["layouts"])


async def _recorded_profile(manager, info, variable: str):
    if not info.tmux_session or is_remote_info(info):
        return None
    pane = await read_pane_profile(manager.tmux_socket_name(), info.tmux_session, variable)
    if not (pane.readable and pane.value):
        return None
    path = os.path.expanduser(pane.value)
    return os.path.normpath(path) if os.path.isabs(path) else None


async def skill_rewriter(request: Request, layout, infos):
    manager = request.app.state.session_manager
    claude_home, codex_root = user_scope_roots(request)
    names = {}
    for info in suggestions.target_infos(layout, infos):
        family = translate_mod.family_of(info)
        if family is None:
            continue
        sigil = translate_mod.FAMILY_SIGIL[family]
        profile = await _recorded_profile(manager, info, "CLAUDE_CONFIG_DIR" if sigil == "/" else "CODEX_HOME")
        wd = str(info.session.working_dir)

        def scan(sigil=sigil, profile=profile, wd=wd):
            found = suggestions._global_names(sigil, profile, claude_home, codex_root)
            found.update(suggestions._project_names(sigil, wd))
            return frozenset(c.lstrip("/$") for c in found)
        names[id(info)] = await run_in_threadpool(scan)

    def rewrite(info, text: str) -> str:
        return translate_mod.translate(text, translate_mod.family_of(info),
                                       names.get(id(info), frozenset()))
    return rewrite


@router.get("/{layout_uuid}/skills", response_model=SkillSuggestionsResponse,
            dependencies=[Depends(require_auth)])
async def layout_skills(layout_uuid: str, request: Request,
                        sigil: Literal["/", "$"] = Query("/")) -> SkillSuggestionsResponse:
    """Skills to complete after ``sigil`` in the Layout's command bar.

    Description: "/" lists Claude Code skills and commands, "$" Codex skills.
      Global ones always; project ones only when every member a broadcast
      would reach has them.
    Raises: HTTPException 404 ``layout_not_found``, 503 ``layouts_unavailable``.
    Example: GET /api/v1/layouts/<uuid>/skills?sigil=%24
    """
    try:
        layout = await run_in_threadpool(run_on_store, store.get_layout, layout_uuid)
    except store.LayoutNotFound as exc:
        raise layout_error(404, "layout_not_found", str(exc))
    except (DatastoreUnreadableError, store.LayoutsUnavailable, OSError) as exc:
        raise layout_error(503, "layouts_unavailable", str(exc))
    targets = suggestions.target_infos(layout, await live_listing(request))
    dirs = [str(t.session.working_dir) for t in targets]
    variable = "CLAUDE_CONFIG_DIR" if sigil == "/" else "CODEX_HOME"
    manager = request.app.state.session_manager
    profiles = [await _recorded_profile(manager, t, variable) for t in targets]
    claude_home, codex_root = user_scope_roots(request)
    found = await run_in_threadpool(
        lambda: suggestions.suggest(sigil, working_dirs=dirs, claude_home=claude_home,
                                    codex_skills_root=codex_root,
                                    profile_dirs=profiles))
    return SkillSuggestionsResponse(sigil=sigil, targets=len(dirs),
                                    skills=[SkillSuggestion(**s) for s in found])
