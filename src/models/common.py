
from typing import Optional
from pydantic import BaseModel, Field



class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    code: int = Field(..., description="HTTP status code")


class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool = True
    message: str = ""


class HealthResponse(BaseModel):
    """Health check response for menu bar app."""
    status: str = Field(..., description="Server status (running/stopped)")
    uptime: int = Field(..., description="Server uptime in seconds")
    session_name: Optional[str] = Field(None, description="Current session name/working dir")
    local_server_count: int = Field(0, description="Number of detected local dev servers")
    version: str = Field(
        "", description="Version of the running server code, frozen at startup"
    )
