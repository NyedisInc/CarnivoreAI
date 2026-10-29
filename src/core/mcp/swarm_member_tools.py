
from __future__ import annotations

from typing import Any, Optional

from src.core.mcp import route_adapters as ra
from src.core.mcp import session_target
from src.core.mcp.common import ToolError


def _name(target: Optional[session_target.SessionTarget]) -> str:
    return (target.info.tmux_session if target is not None and target.live else
            target.tmux_name if target is not None else None) or "a session"


def _uuid(call: ra.Call) -> str:
    if call.session_uuid is None:
        raise ToolError("that session has no stored row")
    return call.session_uuid


async def _join(call: ra.Call) -> Any:
    from src.models.swarm import SwarmJoinRequest

    req = SwarmJoinRequest(session_uuid=_uuid(call), specialty=call.args.get("specialty"), confirm_restart=True,
                           create_project_agent=bool(call.args.get("create_project_agent")))
    return await call.route(req, call.request)


async def _leave(call: ra.Call) -> Any:
    return await call.route(_uuid(call), call.request, None, confirm_restart=True)


def _join_summary(args: dict, target: Optional[session_target.SessionTarget]) -> str:
    extra = " (and create its project agent first)" if args.get("create_project_agent") else ""
    return f"make {_name(target)} a swarm agent{extra}: it restarts and stops whatever it is doing; its conversation is kept"


def _leave_summary(_args: dict, target: Optional[session_target.SessionTarget]) -> str:
    return f"take {_name(target)} out of the swarm: it restarts as a plain session; its conversation is kept, its cards go back to the queue"


SPECS = (
    ra.RouteTool(
        name="swarm_join", route="src.api.swarm_member_routes:join_swarm", gate=ra.ACT,
        description="Make a session a Swarm member (a feature agent under its project agent). It restarts on the same conversation "
                    "with the Swarm tools. Waits for the owner's approval every time. A project with no agent refuses unless "
                    "create_project_agent is true.",
        properties={"specialty": {"type": "string", "description": "optional: the domain it owns (60 characters at most)"},
                    "create_project_agent": {"type": "boolean", "description": "turn the project's agent on first when it has none"}},
        reach=session_target.STORED, needs_uuid=True, local_only=False, invoke=_join, summary=_join_summary, example={},
    ),
    ra.RouteTool(
        name="swarm_leave", route="src.api.swarm_member_routes:leave_swarm", gate=ra.ACT,
        description="Take a Swarm member out of the Swarm: it restarts as a plain session on the same conversation, its cards go "
                    "back to the queue and its agent is parked (a rejoin restores it). Waits for the owner's approval every time.",
        reach=session_target.STORED, needs_uuid=True, local_only=False, invoke=_leave, summary=_leave_summary, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
