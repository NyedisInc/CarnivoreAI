
from pydantic import BaseModel

SWARM_SWITCH_KEY = "swarm_switch"


class SwarmSwitchConfig(BaseModel):
    """The global Swarm switch.

    Extra keys are ignored (pydantic's default), so a later build's extra field never turns a stored off back on.
    """

    enabled: bool = True
