from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class McpDropInfo(BaseModel):
    """One MCP server that is not connected, in the original shape (docs/session-status.md, "MCP drops")."""
    name: str = Field(description="Server name; the exact config name when `exact`")
    state: Literal["dropped", "failed", "needs_auth"] = Field(description="Why it is not connected")
    at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of the evidence saying so")
    exact: bool = Field(description="True when `name` can be handed to `/mcp reconnect <name>` as is")
    source: Literal["transcript", "server", "client_log", "process", "probe"] = Field(
        default="transcript",
        description=("Who said so: the transcript, this server's own first-hand record (carnivore), the session's "
                     "MCP client log, the stdio process tree, or Carnivore's reachability probe"),
    )


class McpServerHealthInfo(BaseModel):
    """One MCP server of a session with its measured state (#1678; docs/session-status.md, "MCP servers")."""
    name: str = Field(description="Server name; the exact config name when `exact`")
    transport: Literal["stdio", "http", "sse", "proxy", "unknown"] = Field(description="How the agent reaches it")
    state: Literal["connected", "down", "needs_auth", "unknown"] = Field(
        description="connected, down, needs_auth, or unknown (not measurable, or the link is not visible)"
    )
    reason: str = Field(description="Stable reason code; the catalog renders mcp.reason.<code>")
    source: Literal["first_hand", "client_log", "process", "probe", "transcript"] = Field(
        description="The evidence that decided the state"
    )
    detail: Optional[str] = Field(default=None, description="Short measured qualifier: an error code or HTTP status")
    at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of the deciding evidence")
    exact: bool = Field(default=True, description="True when `name` can be handed to `/mcp reconnect <name>` as is")


class CarnivoreLinkInfo(BaseModel):
    """What THIS server process saw of a session's carnivore MCP client (docs/mcp-server.md, "Per-session link state")."""
    state: Literal["connected", "dropped", "unknown"] = Field(description="The link's first-hand state")
    initialized_at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of its last initialize here")
    last_request_at: Optional[str] = Field(default=None, description="ISO 8601 UTC time of its last accepted request here")


class McpHealthInfo(BaseModel):
    """A session's MCP servers, measured, or the field is null (not measured).

    Mirrors ``src.core.mcp_health.fold.McpHealth``. ``servers`` is every configured or observed server with its
    state; ``dropped`` is its down and needs-auth subset in the original shape. An empty ``dropped`` is a MEASURED
    "nothing down"; null on the wrapper is "nothing measured", never "all well".
    """
    servers: List[McpServerHealthInfo] = Field(
        default_factory=list, description="Every server with its measured state, by name; empty before the first measure"
    )
    dropped: List[McpDropInfo] = Field(default_factory=list, description="Servers down or needing auth")
    carnivore: Optional[CarnivoreLinkInfo] = Field(
        default=None, description="This server's first-hand view of the session's carnivore link, when judged"
    )
