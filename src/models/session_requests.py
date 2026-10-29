
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from .model_ids import describe_model_id_rejection, is_valid_model_id



class CreateSessionRequest(BaseModel):
    """Request model for creating a new session."""
    working_dir: Optional[str] = Field(
        None,
        description="Override working directory (defaults to configured path)"
    )
    auto_start_claude: bool = Field(
        True,
        description="Auto-launch claude-code CLI"
    )
    copy_templates: bool = Field(
        False,
        description="Copy template files to working directory"
    )
    project_name: Optional[str] = Field(
        None,
        description="Optional human-readable project display name"
    )
    # launch command
    label: Optional[str] = Field(
        None,
        description="Name for the new session; also passed to claude as --name"
    )
    project_parent_dir: Optional[str] = Field(
        None,
        description="The folder a new project or agent lives in, used as-is"
    )
    cols: Optional[int] = Field(
        None,
        description="Client-measured terminal columns (xterm cell grid width)"
    )
    rows: Optional[int] = Field(
        None,
        description="Client-measured terminal rows (xterm cell grid height)"
    )
    agent_type: Optional[str] = Field(
        None,
        description="Agent CLI to launch ('claude' | 'codex' | 'hermes' | 'openclaw' | a configured wrapper id); overrides project default",
    )
    model: Optional[str] = Field(
        None,
        description="OpenRouter model id; None launches Claude directly via 'keyc'",
    )
    host_key: Optional[str] = Field(
        None,
        description="hosts.key of the machine to run on; omitted or 'local' is this machine",
    )

    account_id: Optional[str] = Field(
        None,
        description=(
            "a claude account id on this computer (GET /launch/accounts); the agent launches on it "
            "instead of the active account. Omit to use the active account"
        ),
    )
    account_pinned: bool = Field(
        False,
        description="With account_id: true saves it as this agent's account (every later restart and wake uses it)",
    )

    opening_prompt: Optional[str] = Field(
        None,
        description="First prompt for a claude or codex session (max 8 KiB); never re-sent on restart",
    )

    @field_validator("opening_prompt")
    @classmethod
    def _validate_opening_prompt(cls, v: Optional[str]) -> Optional[str]:
        """Refuse a prompt that could not travel as one literal argument."""
        from .blueprints import check_opening_prompt

        return check_opening_prompt(v)

    @field_validator("model")
    @classmethod
    def _validate_model_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not is_valid_model_id(v):
            raise ValueError(describe_model_id_rejection(v))
        return v


class CommandRequest(BaseModel):
    """Request model for sending a command."""
    command: str = Field(..., description="Command to execute in the session")


class SetUnreadRequest(BaseModel):
    """Request body for ``PATCH /sessions/{session_name}/unread``.
    """
    unread: bool = Field(
        ..., description="True to mark unread for followup, False to clear"
    )


class ForkSessionResponse(BaseModel):
    """Response for ``POST /sessions/{session_name}/fork``.

    ``lineage_recorded`` is its own field rather than folded into
    ``success`` on purpose. The tmux session can be created successfully
    and the lineage stamp still fail to land - the fork EXISTS and works
    either way, it just is not linked to its parent in the tree. Reporting
    that as an outright failure would be wrong (the user has a working
    forked session) and reporting it as an unqualified success would hide
    a real gap. It is the third outcome, given its own field.
    """
    success: bool = True
    session: dict = Field(default_factory=dict)
    parent_session_id: Optional[int] = None
    lineage_recorded: bool = False
    detail: Optional[str] = None


class RenameSessionRequest(BaseModel):
    """Request body for ``PATCH /api/v1/sessions/{session_id}/name``.

    ``new_name`` is a LABEL, not a tmux session name. It is validated by
    ``session_label.validate_label``, which accepts anything printable -
    spaces, punctuation, mixed case, non-ASCII - and refuses only what
    cannot be rendered: empty, over 200 characters, or carrying a control
    character such as a newline.

    The strict ``[A-Za-z0-9_-]`` charset this used to carry existed
    because the value was handed straight to ``tmux rename-session``. It
    no longer is: the endpoint writes ``sessions.title`` and the tmux
    name never moves, which is what stops a rename from splitting one
    session into two rows.
    """
    new_name: str = Field(
        ...,
        description=(
            "New session label (1-200 chars, any printable text "
            "including spaces)"
        ),
    )
