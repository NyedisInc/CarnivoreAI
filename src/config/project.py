
from typing import Literal, Optional

from pydantic import BaseModel


class ProjectConfig(BaseModel):
    """Configuration for a predefined project.
    """
    name: str
    path: str
    description: Optional[str] = None
    agent_type: Literal["claude", "codex", "hermes", "openclaw"] = "claude"
