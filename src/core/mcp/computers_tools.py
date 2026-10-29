
from __future__ import annotations

from typing import Any

from src.core.computers import add_preview
from src.core.mcp import agent_tool_switches, route_adapters as ra
from src.core.mcp.common import ToolError

SHOWN_ON = "pack, computers"

UNLOCK_NOTE = ("After the join completes the Pack tools unlock (pack_op_get, project_migrate, session_move and the rest). "
               "A Codex or plain-HTTP pane needs a restart or /mcp reconnect to see them.")

_SSH = {"ssh_target": {"type": "string", "maxLength": 254, "description": "an ssh alias or user@host"},
        "ssh_port": {"type": "integer", "minimum": 1, "maximum": 65535}}
_COMPUTER = {"computer": {"type": "string", "maxLength": 64, "description": "a computer's install id, as computers_list lists it"}}


DETAIL_LINK, DETAIL_SPECS = "link", "specs"


def _list(call: ra.Call) -> Any:
    detail = call.args.get("detail", DETAIL_LINK)
    if detail not in (DETAIL_LINK, DETAIL_SPECS):
        raise ToolError(f"detail must be {DETAIL_LINK} or {DETAIL_SPECS}")
    if detail == DETAIL_LINK:
        if "agents" in call.args:
            raise ToolError("agents goes with detail specs")
        return call.route(call.request)
    from src.api import pack_machines_routes

    return pack_machines_routes.get_machines(call.request, bool(call.args.get("agents", False)))


def _unlock_note() -> dict:
    return {} if agent_tool_switches.current().pack else {"note": UNLOCK_NOTE}


async def _invite(call: ra.Call) -> Any:
    answer = await call.route(call.request)
    return {"id": answer["id"], "expires_at": answer["expires_at"], "attempts_left": answer.get("attempts_left", 3),
            "shown_on": SHOWN_ON, **_unlock_note()}


def _invite_delete(call: ra.Call) -> Any:
    return call.route(call.args["invite"], call.request)


def _remove(call: ra.Call) -> Any:
    return call.route(call.args["computer"], call.request)


def _direction(call: ra.Call) -> Any:
    from src.api.computers_routes import DirectionBody

    if call.args["direction"] != "one_way":
        raise ToolError("only the owner lets a computer control this one, in the app")
    return call.route(call.args["computer"], DirectionBody(direction="one_way"), call.request)


def _add_body(call: ra.Call, cls: Any) -> Any:
    return cls(**{k: v for k, v in call.args.items() if v is not None})


def _add_preview(call: ra.Call) -> Any:
    from src.api.computers_routes import AddPreviewBody

    return call.route(_add_body(call, AddPreviewBody), call.request)


async def _add(call: ra.Call) -> Any:
    from src.api.computers_routes import AddBody

    answer = await call.route(_add_body(call, AddBody), call.request)
    return {**answer, **_unlock_note()}


def _add_summary(args: dict, _target: Any) -> str:
    target, port, fp = str(args.get("ssh_target", ""))[:254], args.get("ssh_port"), str(args.get("host_key_sha256", ""))[:64]
    seen = add_preview.recall(target, port if isinstance(port, int) else None)
    if seen is None or seen["host_key_sha256"] != fp:
        trust, then = "host key not previewed", "preview it first"
    else:
        trust = {"same": "already trusted", "new": "new, it will be trusted"}.get(seen["known"], "CHANGED from the trusted key")
        then = ", ".join(seen["blockers"]) or "install carnivore there and join this pack"
    return f"add computer {target}{f':{port}' if port else ''}, host key {fp} ({trust}), {then}"


def _leave(call: ra.Call) -> Any:
    return call.route(call.request)


SPECS = (
    ra.RouteTool(
        name="computers_list", route="src.api.computers_routes:get_computers", gate=ra.READ,
        description="The computers linked to this one: label, transport (tls or ssh), role, state, direction, last link, this computer's "
                    "own role and link state, and the open invites (never their codes). detail specs instead lists every Pack computer's "
                    "specs, live load, disk, battery, reserve level, restrictions, link state and the master.",
        properties={"detail": {"type": "string", "enum": [DETAIL_LINK, DETAIL_SPECS], "description": "link (default) or specs"},
                    "agents": {"type": "boolean", "description": "specs only; accepted for per-agent load, ignored until it ships"}},
        invoke=_list, example={},
    ),
    ra.RouteTool(
        name="computer_invite", route="src.api.computers_routes:post_invite", gate=ra.ACT,
        description="Open a code for adding a computer to this one (15 minutes, three tries). Always waits for the owner's approval. "
                    "The code and link are not returned: the owner reads them in Pack, Computers.",
        properties={}, invoke=_invite, summary=lambda args, _t: "open a code for adding a computer (15 minutes)", example={},
    ),
    ra.RouteTool(
        name="computer_invite_delete", route="src.api.computers_routes:delete_invite", gate=ra.ARRANGE,
        description="Cancel an open invite by id (as computers_list lists it).",
        properties={"invite": {"type": "string", "maxLength": 16}}, required=("invite",), invoke=_invite_delete, example={"invite": "49759e95"},
    ),
    ra.RouteTool(
        name="computer_remove", route="src.api.computers_routes:delete_computer", gate=ra.ACT,
        description="Remove a linked computer: it is told, its access to this computer ends and its sessions leave the lists. "
                    "Always waits for the owner's approval.",
        properties=_COMPUTER, required=("computer",), invoke=_remove,
        summary=lambda args, _t: f"remove the computer {args.get('computer', '')[:64]}", example={"computer": "hosta-install-id"},
    ),
    ra.RouteTool(
        name="computer_direction_set", route="src.api.computers_routes:put_direction", gate=ra.ACT,
        description="Stop a computer from controlling this one (direction one_way): this computer still drives it. Only one_way is "
                    "open to an agent; letting a computer control this one is the owner's choice in the app.",
        properties={**_COMPUTER, "direction": {"type": "string", "enum": ["both", "one_way"]}}, required=("computer", "direction"),
        invoke=_direction, summary=lambda args, _t: f"make the computer {args.get('computer', '')[:64]} one way (it cannot control this one)",
        example={"computer": "hosta-install-id", "direction": "one_way"},
    ),
    ra.RouteTool(
        name="computer_add_preview", route="src.api.computers_routes:post_add_preview", gate=ra.READ,
        description="Check a computer before adding it over ssh: its ssh host key (and whether this computer already trusts it), whether keys log "
                    "in, and what is blocking (no console login, no homebrew, an installer that is too old, already set up or joined). Changes nothing.",
        properties=_SSH, required=("ssh_target",), invoke=_add_preview, example={"ssh_target": "acme@hosta"},
    ),
    ra.RouteTool(
        name="computer_add", route="src.api.computers_routes:post_add", gate=ra.ACT,
        description="Install Carnivore on a computer over ssh and join it to this pack. Pass the host_key_sha256 that computer_add_preview "
                    "returned. Always waits for the owner's approval; the result is a job_id, follow it in computers_list (add_jobs).",
        properties={**_SSH, "host_key_sha256": {"type": "string", "maxLength": 80, "description": "the SHA256:... fingerprint the preview returned"}},
        required=("ssh_target", "host_key_sha256"), invoke=_add, summary=_add_summary,
        example={"ssh_target": "acme@hosta", "host_key_sha256": "SHA256:" + "A" * 43},
    ),
    ra.RouteTool(
        name="computer_leave", route="src.api.computers_routes:post_leave", gate=ra.ACT,
        description="Leave the pack this computer joined: main is told and this computer stands alone again. "
                    "Always waits for the owner's approval.",
        properties={}, invoke=_leave, summary=lambda args, _t: "leave the pack this computer joined", example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
