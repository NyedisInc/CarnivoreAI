
from typing import List

from pydantic import BaseModel, Field

from src.core.agent_wrappers import AgentWrapper


class AgentsConfig(BaseModel):
    """The ``agents`` block of config.json: the launch wrappers.
    """
    wrappers: List[AgentWrapper] = Field(default_factory=list)
