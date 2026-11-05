
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError
from src.core.notifications.catalog_lines import read_prefixed

_SIDELOAD = "plugin_sideload_add"
_REMOVE = "plugin_sideload_remove"
_WARNING_KEY = "plugins.page.sideload.warning.risk"
SIDELOAD_WARNING: str = read_prefixed((_WARNING_KEY,))[_WARNING_KEY]
_KIND = {"type": "string", "enum": ["cplug", "theme", "skill", "plugin"], "description": "only when two kinds hold the same name"}
_PATH_RULES = ("an absolute folder on this computer; the kind (sidecar plugin, theme, skill or Claude Code plugin) is read from its "
               "manifest. It installs unverified and still needs the owner's consent to run. Refused with sideload_off while the developer sideload switch is off (no tool turns it on). A theme, skill or "
               "Claude Code plugin that runs code (hooks, MCP servers, scripts, an effects file) is refused with consent_required: only "
               "the owner gives that consent, on the Plugins page.")
_NAME = {"name": {"type": "string", "maxLength": 64, "description": "the install name (default: the id in the plugin's cplug.json)"}}


def _require_on(request: Any) -> None:
    from src.cplugs.host import sideload_routes

    live = getattr(getattr(getattr(request, "app", None), "state", None), "sidecar_runtime", None)
    if live is None:
        return
    try:
        sideload_routes.require_on(live.state_dir)
    except HTTPException as exc:
        raise ToolError(f"refused ({exc.status_code}): sideload_off: the developer sideload switch is off; only the owner turns it on, "
                        "on the Plugins page") from exc


async def _load(call: ra.Call) -> Any:
    return _warned(await _run_load(call))


def _warned(answer: Any) -> Any:
    return {**answer, "warning": SIDELOAD_WARNING} if isinstance(answer, dict) else answer


async def _run_load(call: ra.Call) -> Any:
    from src.cplugs.host import sideload_git_routes, sideload_routes

    _require_on(call.request)
    args = call.args
    if ("path" in args) == ("git_url" in args):
        raise ToolError("plugin_sideload_add takes path (a folder) or git_url (a repository), exactly one")
    if "path" in args:
        if "ref" in args or "subdir" in args:
            raise ToolError("ref and subdir only go with git_url")
        return await sideload_routes.post_sideload(sideload_routes.SyncBody(path=args["path"], name=args.get("name")), call.request)
    body = sideload_git_routes.GitBody(url=args["git_url"], ref=args.get("ref"), subdir=args.get("subdir"), name=args.get("name"))
    return await sideload_git_routes.post_sideload_git(body, call.request)


async def _remove(call: ra.Call) -> Any:
    _require_on(call.request)
    return await call.route(call.request, name=call.args["name"], kind=call.args.get("kind"))


def _load_summary(args: dict, _target: Any) -> str:
    where = f"folder {str(args.get('path'))[:200]}" if "path" in args else f"git {str(args.get('git_url'))[:200]}"
    if args.get("ref"):
        where += f" at {str(args['ref'])[:64]}"
    return f"sideload a plugin (unreviewed code) from {where}. warning: {SIDELOAD_WARNING}"


def _remove_summary(args: dict, _target: Any) -> str:
    return f"remove the sideloaded plugin {str(args.get('name'))[:64]}"


SPECS = (
    ra.RouteTool(
        name=_SIDELOAD, route="src.cplugs.host.sideload_routes:post_sideload", gate=ra.ACT,
        description="Sideload or re-sync your own plugin from path or git_url as local/<name>. Always waits for the owner. "
                    "Warning: " + SIDELOAD_WARNING,
        properties={"path": {"type": "string", "maxLength": 1024, "description": _PATH_RULES},
                    "git_url": {"type": "string", "maxLength": 2048, "description": "or a git source: https or ssh, with optional ref and subdir"},
                    "ref": {"type": "string", "maxLength": 255, "description": "branch, tag or commit"},
                    "subdir": {"type": "string", "maxLength": 512}, **_NAME},
        invoke=_load, summary=_load_summary, request_check=_require_on, example={"path": "/tmp/clock"},
    ),
    ra.RouteTool(
        name=_REMOVE, route="src.cplugs.host.sideload_routes:delete_sideload", gate=ra.ACT,
        description="Remove one sideloaded plugin of any kind by name (kind only when two kinds share the name): a sidecar plugin stops "
                    "and its copied code goes; a theme, skill or Claude Code plugin folder moves to the trash; a git checkout goes; data and grants "
                    "stay. Always waits for the owner. Refused (sideload_off) while the developer sideload switch is off.",
        properties={"name": {"type": "string", "maxLength": 64}, "kind": _KIND}, required=("name",),
        invoke=_remove, summary=_remove_summary, request_check=_require_on, example={"name": "clock"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
