
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pathlib import Path
from src.config import settings
from src.core import slash_favorites
from src.core.slash_command_discovery import (
    build_command_groups,
    command_groups_to_dict,
)
from src.models import ToggleFavoriteCommandRequest
from src.models.agents import ReorderFavoritesRequest, SetFavoriteColorRequest
from typing import Optional

from src.api.auth import require_auth

logger = structlog.get_logger()
router = APIRouter()


def _config_path() -> Path:
    return Path(settings.auth_config_file).expanduser()


@router.get("/config/common-commands", dependencies=[Depends(require_auth)])
async def get_common_commands():
    """
    Get the user's starred slash commands, with short descriptions.

    Config entries may be bare strings (historical form) or objects with
    a user-authored ``description``; see
    ``src/core/slash_command_labels.py``.

    Raises:
        HTTPException: If config loading fails
    """
    try:
        body = slash_favorites.payload(_config_path())
        logger.debug(
            "common_commands_retrieved",
            count=len(body["commands"]), defaulted=body["defaulted"],
        )
        return body

    except FileNotFoundError as e:
        logger.error("auth_config_missing", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Configuration not found. Run setup_auth.py first."
        )
    except Exception as e:
        logger.error("common_commands_retrieval_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve common commands: {str(e)}"
        )


@router.post("/config/common-commands/favorite", dependencies=[Depends(require_auth)])
async def toggle_favorite_command(body: ToggleFavoriteCommandRequest):
    """
    Star or unstar one slash command, and return the new chip row.

    Replaces the hand-picked ``common_slash_commands`` notion with a
    user-chosen one: the SAME config key, written by a star in the
    palette instead of by hand-editing JSON. Every existing entry is
    preserved in its original form (bare string or
    ``{"command", "description"}`` object); a newly starred command is
    appended as a bare string, which is the historical form.

    Starring the first time on a config that never declared the key
    MATERIALIZES the built-in defaults first, so unstarring one of them
    actually removes it rather than writing a list that still contains
    it. An empty result is kept as an empty DECLARED list, never
    re-seeded - the user unstarred everything on purpose.

    Returns the same body as ``GET /config/common-commands`` so the
    client repaints from the authoritative post-write state rather than
    guessing what it just did.

    Raises:
        HTTPException: 400 on a blank command or past the favorites cap,
            500 if config.json is missing or unreadable.
    """
    try:
        path = _config_path()
        raw, declared = slash_favorites.read_raw(path)
        entries = slash_favorites.toggle(raw, declared, body.command, body.favorite)
        slash_favorites.write(path, entries)
        settings._auth_config_cache = None
        result = slash_favorites.payload(path)
        logger.info(
            "common_command_favorite_toggled",
            command=body.command, favorite=body.favorite,
            count=len(result["commands"]),
        )
        return result
    except slash_favorites.FavoritesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        logger.error("auth_config_missing", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Configuration not found. Run setup_auth.py first."
        )
    except ValueError as e:
        logger.error("common_command_favorite_config_invalid", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


def _stale_conflict(path: Path, error: Exception) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "favorites_stale",
            "message": str(error),
            "current": slash_favorites.payload(path),
        },
    )


def _favorites_write(apply) -> dict:
    path = _config_path()
    try:
        apply(path)
    except slash_favorites.FavoritesStale as e:
        raise _stale_conflict(path, e)
    except slash_favorites.FavoritesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        logger.error("auth_config_missing", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Configuration not found. Run setup_auth.py first."
        )
    except ValueError as e:
        logger.error("common_command_favorite_config_invalid", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    settings._auth_config_cache = None
    return slash_favorites.payload(path)


@router.post("/config/common-commands/color", dependencies=[Depends(require_auth)])
async def set_favorite_color(body: SetFavoriteColorRequest):
    """
    Mark one favorite with a colour from the fixed swatch set, or clear it.

    Stored in its own ``slash_favorite_colors`` key, never in the list's
    entries (see ``src/core/slash_favorites.py``). A command that is no
    longer a favorite answers 409 with the current row.

    Returns the same body as ``GET /config/common-commands``.
    """
    result = _favorites_write(
        lambda path: slash_favorites.apply_color(path, body.command, body.color)
    )
    logger.info("common_command_color_set", command=body.command, color=body.color)
    return result


@router.post("/config/common-commands/order", dependencies=[Depends(require_auth)])
async def reorder_favorites(body: ReorderFavoritesRequest):
    """
    Put the favorites in a new order: the chip row's drag and drop.

    ``commands`` must name exactly the stored favorites, each once; any
    other set is a stale view and answers 409 with the current row. Every
    entry keeps its original form.

    Returns the same body as ``GET /config/common-commands``.
    """
    result = _favorites_write(
        lambda path: slash_favorites.apply_order(path, body.commands)
    )
    logger.info("common_commands_reordered", count=len(body.commands))
    return result


def _user_scope_roots(request: Request) -> tuple[Optional[Path], Optional[Path]]:
    services = getattr(request.app.state, "services", None)
    install_roots = getattr(services, "install_roots", None)
    if install_roots is None:
        return (None, None)

    claude_home: Optional[Path] = None
    codex_skills_root: Optional[Path] = None
    for target in install_roots.targets_for("skill", "global", None):
        if target.harness == "claude":
            claude_home = target.leaf_dir.parent
        elif target.harness == "codex":
            codex_skills_root = target.leaf_dir
    return (claude_home, codex_skills_root)

@router.get("/config/slash-commands", dependencies=[Depends(require_auth)])
async def get_slash_commands(
    request: Request, project_path: Optional[str] = None
):
    """
    A separate endpoint from `/config/common-commands` (Task 2's decision,
    see project docs): common-commands is a small hand-curated "favorites"
    row shown at the top of the palette and its response shape (a bare
    list of command strings) stays exactly as-is for existing consumers.
    This endpoint serves the full palette body underneath it, grouped for
    direct rendering - a different shape for a different purpose, not a
    breaking change to the old one.

    Args:
        project_path: absolute path to the currently active project's
            working directory, used for project-scope discovery. Omit to
            skip project-scope entirely (e.g. before any session is open).

    Returns:
        {"groups": [{"id", "label", "commands": [{"command", "args",
        "description", "type", "alias_of"}, ...]}, ...]} in a fixed
        group order - see `build_command_groups()`.

    Raises:
        HTTPException: on unexpected discovery failure. Missing/partial
            data sources (no plugins installed, no project scope, a
            stale/absent scraped JSON) are NOT errors - they just yield
            fewer groups.
    """
    try:
        claude_home, codex_skills_root = _user_scope_roots(request)
        groups = build_command_groups(
            project_path=project_path,
            claude_home=claude_home,
            codex_skills_root=codex_skills_root,
        )
        payload = command_groups_to_dict(groups)
        logger.debug(
            "slash_commands_retrieved",
            group_count=len(payload),
            command_count=sum(len(g["commands"]) for g in payload),
            project_scoped=bool(project_path),
        )
        return {"groups": payload}
    except Exception as e:
        logger.error("slash_commands_retrieval_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve slash commands: {str(e)}"
        )
