
from fastapi import APIRouter, Depends, Request, Response

from src.api.auth import require_auth
from src.core.companion_shell import ensure
from src.models import CompanionShell

router = APIRouter(tags=["sessions"])


@router.post("/sessions/{session_id}/shell", response_model=CompanionShell, dependencies=[Depends(require_auth)])
async def open_shell(request: Request, response: Response, session_id: str) -> CompanionShell:
    """Open the agent's companion shell, creating it on first use (201), else return or restart it (200).

    Inputs: session_id (str) - the agent's id. Output: CompanionShell.
    Raises: 404 unknown_session; 409 remote_agent, agent_not_running, agent_not_recorded, is_a_shell, folder_missing,
      shell_unavailable.
    """
    shell = await ensure.ensure(request, session_id)
    if shell.state == "created":
        response.status_code = 201
    return shell


@router.get("/sessions/{session_id}/shell", response_model=CompanionShell, dependencies=[Depends(require_auth)])
async def get_shell(request: Request, session_id: str) -> CompanionShell:
    """The agent's running companion shell with its measured pane, or 404 ``none``. Never creates.

    Inputs: session_id (str) - the agent's id. Output: CompanionShell.
    """
    return await ensure.read(request.app, session_id)
