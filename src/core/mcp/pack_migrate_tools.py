
from __future__ import annotations

import json
from typing import Any

from src.core.mcp import route_adapters as ra

_PROJECT = {"project": {"type": "string", "description": "the project's display name (projects_list)"}}
_COMPANY = {"company": {"type": "string", "description": "the company's name or id (companies_list)"}}
_PLAN = {"machine": {"type": "string", "maxLength": 200, "description": "the paired computer to move to (computers_list, detail specs)"},
         "rung": {"type": "string", "enum": ["carried", "tar"], "description": "force how the code travels (default: the best the folder allows)"}}
_APPLY = {**_PLAN, "plan_fingerprint": {"type": "string", "maxLength": 64, "description": "the plan_fingerprint of the plan you read"}}


def _body(call: ra.Call, apply: bool) -> Any:
    from src.api.pack_migrate_routes import MigrateBody

    keys = ("machine", "rung") + (("plan_fingerprint",) if apply else ())
    return MigrateBody(apply=apply, **{k: call.args[k] for k in keys if call.args.get(k) is not None})


def _project(apply: bool):
    return lambda call: call.route(call.args["project"], _body(call, apply))


def _company(apply: bool):
    return lambda call: call.route(call.args["company"], _body(call, apply))


def _back(call: ra.Call) -> Any:
    from src.api.pack_migrate_routes import BackBody

    return call.route(call.args["project"], BackBody(apply=True))


def _op(call: ra.Call) -> Any:
    return call.route(call.args["op_id"])


SPECS = (
    ra.RouteTool(
        name="project_migrate_plan", route="src.api.pack_migrate_routes:migrate_project", gate=ra.READ,
        description="Plan moving a project to a paired computer: the code rung (git clone, carried bundle or one-way tar), the checks "
                    "(live agents are listed; the move stops them itself), what moves, and the plan_fingerprint to quote. Changes nothing.",
        properties={**_PROJECT, **_PLAN}, required=("project", "machine"), invoke=_project(False), example={"project": "demo", "machine": "hosta"},
    ),
    ra.RouteTool(
        name="project_migrate", route="src.api.pack_migrate_routes:migrate_project", gate=ra.ACT,
        description="Move a project to a paired computer: verified there before it becomes home, then kept here as moved_away. Quote "
                    "the plan_fingerprint of project_migrate_plan. Answers an op_id (pack_op_get). Waits for the owner unless Beast Mode is armed.",
        properties={**_PROJECT, **_APPLY}, required=("project", "machine", "plan_fingerprint"), invoke=_project(True),
        summary=lambda args, _t: f"move project {json.dumps(args.get('project'))} to {json.dumps(args.get('machine'))} (it stays here, inactive)",
        example={"project": "demo", "machine": "hosta", "plan_fingerprint": "0123456789abcdef"},
    ),
    ra.RouteTool(
        name="company_migrate_plan", route="src.api.pack_migrate_routes:migrate_company", gate=ra.READ,
        description="Plan moving every active project of a company to one paired computer. Changes nothing.",
        properties={**_COMPANY, **_PLAN}, required=("company", "machine"), invoke=_company(False), example={"company": "acme", "machine": "hosta"},
    ),
    ra.RouteTool(
        name="company_migrate", route="src.api.pack_migrate_routes:migrate_company", gate=ra.ACT,
        description="Move every active project of a company to one paired computer (all staged and verified first, then flipped). "
                    "Quote the plan_fingerprint of company_migrate_plan. Waits for the owner unless Beast Mode is armed.",
        properties={**_COMPANY, **_APPLY}, required=("company", "machine", "plan_fingerprint"), invoke=_company(True),
        summary=lambda args, _t: f"move every project of company {json.dumps(args.get('company'))} to {json.dumps(args.get('machine'))}",
        example={"company": "acme", "machine": "hosta", "plan_fingerprint": "0123456789abcdef"},
    ),
    ra.RouteTool(
        name="project_migrate_back", route="src.api.pack_migrate_routes:migrate_back", gate=ra.ACT,
        description="Bring a moved-away project home: the computer holding it sends it back (same path reversed). Waits for the owner unless Beast Mode is armed.",
        properties=dict(_PROJECT), required=("project",), invoke=_back,
        summary=lambda args, _t: f"bring project {json.dumps(args.get('project'))} back from the computer it moved to",
        example={"project": "demo"},
    ),
    ra.RouteTool(
        name="pack_op_get", route="src.api.pack_migrate_routes:get_op", gate=ra.READ,
        description="State, step, error and children of one migrate (the op_id project_migrate answered).",
        properties={"op_id": {"type": "string", "maxLength": 64}}, required=("op_id",), invoke=_op, example={"op_id": "0123456789abcdef0123456789abcdef"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
