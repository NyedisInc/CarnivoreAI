
from pydantic import BaseModel

SWARM_SWITCH_KEY = "swarm_switch"


class SwarmSwitchConfig(BaseModel):
    """The global Swarm switch.

    Extra keys are ignored (pydantic's default), so a later build's extra field never turns a stored off back on.

    Fields:
        enabled: True (the default) lets the Swarm wake, spawn, sweep and commit; False stops all of it on this
            computer while agents and their memory stay untouched and read-only listings keep working.
    Example: SwarmSwitchConfig(enabled=False)
    """

    enabled: bool = True
