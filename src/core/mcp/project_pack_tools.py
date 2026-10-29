
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.project_tools import _current_name, project_id_arg
from src.core.mcp.write_tools import _via_route, park
from src.core.project_pack.integrity import MODIFIED


def _mb(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "an unknown size"
    return f"{value / 1e9:.2f} GB" if value >= 1e9 else f"{value / 1e6:.0f} MB"


def pack_summary(name: str, plan: Dict[str, Any]) -> str:
    sizes = plan.get("sizes") or {}
    mid = (sizes.get("estimate_low", 0) + sizes.get("estimate_high", 0)) // 2
    text = (f"pack project {json.dumps(name)}: {_mb(sizes.get('logical_bytes'))} in {sizes.get('file_count')} files "
            f"to about {_mb(mid)}; {len(plan.get('repos') or [])} git repos; the originals go to the Trash")
    if plan.get("local_only"):
        text += "; the archive will be the only copy of: " + "; ".join(plan["local_only"])
    return f"{text}; plan {plan.get('fingerprint')}"


def unpack_summary(name: str, plan: Dict[str, Any]) -> str:
    sizes = plan.get("sizes") or {}
    text = f"unpack project {json.dumps(name)}: {_mb(sizes.get('logical_bytes'))} in {sizes.get('file_count')} files"
    warn = (plan.get("integrity") or {}).get("message") if (plan.get("integrity") or {}).get("status") == MODIFIED else ""
    return f"{text}{'; WARNING: ' + warn if warn else ''}; plan {plan.get('fingerprint')}"


def _tool(tool: str, route_name: str, allowed: set, summarize: Callable[[str, dict], str],
          card_args: Callable[[dict], dict]) -> Callable:

    async def handler(manager: Any, caller: AgentCaller, args: dict) -> dict:
        from src.api import project_pack_routes
        from src.models.project_pack import ProjectPackRequest, ProjectUnpackRequest

        if set(args) - allowed:
            raise ToolError(f"{tool} takes only {', '.join(sorted(allowed))}")
        project_id = project_id_arg(args)
        flags = {key: args.get(key, False) for key in ("apply", "accept_local_only") if key in allowed}
        if any(not isinstance(v, bool) for v in flags.values()):
            raise ToolError("apply and accept_local_only must be true or false")
        model = ProjectPackRequest if tool == "project_pack" else ProjectUnpackRequest
        route = getattr(project_pack_routes, route_name)

        async def call(apply: bool, fingerprint: Optional[str] = None) -> dict:
            current = await _current_name(project_id, include_archived=True)
            body = model(**{**flags, "apply": apply, "plan_fingerprint": fingerprint})
            return (await _via_route(route(current, body))).model_dump()

        if not flags["apply"]:
            return _ok(await call(False))
        fingerprint = args.get("plan_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            raise ToolError(f"apply true needs plan_fingerprint: call {tool} with apply false, read the plan, "
                            "and pass back its fingerprint")
        fingerprint = fingerprint.strip()
        plan = await call(False)
        if plan["fingerprint"] != fingerprint:
            raise ToolError(f"the plan changed since it was read (fingerprint {fingerprint} is now "
                            f"{plan['fingerprint']}); read the new plan and quote it")
        if not plan["ok"]:
            failed = "; ".join(c["message"] for c in plan["checks"] if not c["ok"])
            raise ToolError(f"the plan does not pass, so nothing was sent for approval: {failed}")
        name = await _current_name(project_id, include_archived=True)

        async def run(approved: bool) -> dict:
            return _ok(await call(True, fingerprint))

        shown = {"project": project_id, "plan_fingerprint": fingerprint, **flags, **card_args(plan)}
        shown.pop("apply", None)
        return await park(manager, caller, "", "", tool, summarize(name, plan), shown, run,
                          dedupe_key=f"{tool}:{project_id}:{fingerprint}", beast_eligible=False)

    return handler


project_pack = _tool("project_pack", "pack_project", {"project", "apply", "plan_fingerprint", "accept_local_only"},
                     pack_summary, lambda plan: {"local_only": list(plan.get("local_only") or [])})
project_unpack = _tool("project_unpack", "unpack_project", {"project", "apply", "plan_fingerprint"}, unpack_summary,
                       lambda plan: {"integrity_warning": ((plan.get("integrity") or {}).get("message") or "")
                                     if (plan.get("integrity") or {}).get("status") == MODIFIED else ""})

_PROJECT = {"type": "integer", "minimum": 1, "description": "project id from projects_list (include_archived true)"}
_APPLY = {"type": "boolean", "description": "run it (default false: plan only)"}
_FP = {"type": "string", "description": "required with apply: the fingerprint of the plan you read"}

TOOLS: dict = {
    "project_pack": (
        "Compress a HIDDEN project's folder in place into one archive inside it (id from projects_list). apply false "
        "returns the plan and its fingerprint, never waits. apply true needs plan_fingerprint and always waits for the "
        "owner; originals go to the Trash only after the archive is verified. Refused for live sessions, unpushed git "
        "work, cloud-only files. No-remote repos need accept_local_only.",
        {"project": _PROJECT, "apply": _APPLY, "plan_fingerprint": _FP,
         "accept_local_only": {"type": "boolean", "description": "allow repos that exist only in the folder (default false)"}},
        ["project"], project_pack,
    ),
    "project_unpack": (
        "Restore a packed project's folder from its archive (id from projects_list). apply false returns the plan "
        "(with a warning if the archive was changed outside Carnivore) and its fingerprint. apply true needs "
        "plan_fingerprint and always waits for the owner; the archive checksum is checked first.",
        {"project": _PROJECT, "apply": _APPLY, "plan_fingerprint": _FP},
        ["project"], project_unpack,
    ),
}
