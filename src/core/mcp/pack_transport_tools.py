
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi.encoders import jsonable_encoder

from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok

_NAME = {"project": {"type": "string", "description": "the project's display name (projects_list)"}}


def _sync(call: ra.Call) -> Any:
    from src.api.project_transport_routes import SyncBody

    return call.route(call.args["project"], SyncBody(**{k: call.args[k] for k in ("machine", "full") if k in call.args}))


def _account_get(call: ra.Call) -> Any:
    return call.route(call.args["project"])


def _account_set(call: ra.Call) -> Any:
    from src.api.project_transport_routes import GithubAccountBody

    return call.route(call.args["project"], GithubAccountBody(account=call.args.get("account")))


def _card(call: ra.Call) -> Any:
    return call.route(call.args["project"])


SPECS = (
    ra.RouteTool(
        name="project_sync", route="src.api.project_transport_routes:sync_project", gate=ra.ACT,
        description="Carry a project's new commits to its replicas (or its home, from a replica) as a git bundle over the link; "
                    "the receiver keeps them under refs/carnivore/<this install>/. Never touches GitHub. Waits for the owner "
                    "unless Beast Mode is armed.",
        properties={**_NAME, "machine": {"type": "string"}, "full": {"type": "boolean"}}, required=("project",), invoke=_sync,
        summary=lambda args, _t: f"carry new commits of project {json.dumps(args.get('project'))} to {json.dumps(args.get('machine') or 'its replicas')}",
        example={"project": "demo", "machine": "studio"},
    ),
    ra.RouteTool(
        name="project_github_account_get", route="src.api.project_transport_routes:get_github_account", gate=ra.READ,
        description="Which GitHub (gh) account a project uses and where that came from: the project's pointer, its company's, "
                    "the remote's owner, none (a card must ask) or air_gap (it never contacts GitHub).",
        properties=dict(_NAME), required=("project",), invoke=_account_get, example={"project": "demo"},
    ),
    ra.RouteTool(
        name="project_github_account_set", route="src.api.project_transport_routes:put_github_account", gate=ra.ACT,
        description="Set (or clear with null) the gh account a project uses; it must be logged in on this computer. Refused while "
                    "the project is air-gapped. Waits for the owner unless Beast Mode is armed.",
        properties={**_NAME, "account": {"type": ["string", "null"], "maxLength": 64}}, required=("project",), invoke=_account_set,
        summary=lambda args, _t: f"use GitHub account {json.dumps(args.get('account'))} for project {json.dumps(args.get('project'))}",
        example={"project": "demo", "account": "example-owner"},
    ),
    ra.RouteTool(
        name="project_publish_preview", route="src.api.project_transport_routes:get_publish_card", gate=ra.READ,
        description="The publish-private-repo card for a project with no remote: repo name, owner and account found, and what "
                    "the owner must still answer. Creates nothing.",
        properties=dict(_NAME), required=("project",), invoke=_card, example={"project": "demo"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


async def _park_always(manager: Any, caller: AgentCaller, action: str, summary: str, args: dict, allowed: set, route: Any) -> dict:
    from src.core.mcp.write_tools import _via_route, park

    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError(f"{action} does not take {', '.join(extra)}")

    async def run(_approved: bool) -> dict:
        return _ok(jsonable_encoder(await _via_route(route())))

    key = hashlib.sha256(json.dumps([action, args], sort_keys=True, default=str).encode()).hexdigest()
    return await park(manager, caller, "", "", action, summary, args, run, dedupe_key=key, beast_eligible=False)


async def project_publish_repo(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import project_transport_routes as routes

    if not isinstance(args.get("project"), str):
        raise ToolError("project_publish_repo needs project (a display name)")
    body = routes.PublishBody(**{k: args[k] for k in ("owner", "account") if k in args})
    summary = (f"create a PRIVATE GitHub repo for project {json.dumps(args['project'])}"
               + (f" under {json.dumps(args['owner'])}" if args.get("owner") else "")
               + (f" as account {json.dumps(args['account'])}" if args.get("account") else ""))
    return await _park_always(manager, caller, "project_publish_repo", summary, args, {"project", "owner", "account"},
                              lambda: routes.post_publish_repo(args["project"], body))


async def pack_gh_login_add(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import pack_gh_login_routes as routes

    if not isinstance(args.get("machine"), str) or not isinstance(args.get("account"), str):
        raise ToolError("pack_gh_login_add needs machine and account (strings)")
    body = routes.GhLoginBody(machine=args["machine"], account=args["account"])
    summary = f"log {json.dumps(args['machine'])}'s gh into GitHub account {json.dumps(args['account'])} (the token crosses once, never shown)"
    return await _park_always(manager, caller, "pack_gh_login_add", summary, args, {"machine", "account"}, lambda: routes.gh_login(body))


WRITE_TOOLS["project_publish_repo"] = (
    "Create a PRIVATE GitHub repo for a project with no remote and push its first commit (secret scan first). Always waits "
    "for the owner, even in Beast Mode. Always private; no visibility input.",
    {**_NAME, "owner": {"type": "string", "maxLength": 64}, "account": {"type": "string", "maxLength": 64}}, ["project"],
    project_publish_repo,
)
WRITE_TOOLS["pack_gh_login_add"] = (
    "Log a paired computer's gh into one of this computer's gh accounts; the token crosses once, never shown or stored. Always "
    "waits for the owner, even in Beast Mode. The other computer must allow receiving credentials.",
    {"machine": {"type": "string", "maxLength": 200}, "account": {"type": "string", "maxLength": 64}}, ["machine", "account"],
    pack_gh_login_add,
)
