
from __future__ import annotations

import re
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator

AUTO_SLEEP_KEY = "auto_sleep"

DEFAULT_IDLE_MINUTES = 60

DEFAULT_UNREAD_BLOCKS_SLEEP = False
DEFAULT_UNREAD_IDLE_MINUTES = DEFAULT_IDLE_MINUTES

MIN_IDLE_MINUTES = 5

MAX_IDLE_MINUTES = 7 * 24 * 60

MAX_KEEP_AWAKE = 500

MAX_PIN_DEVICES = 20

MAX_PINS_PER_DEVICE = 200

_DEVICE_SHAPE = re.compile(r"^[0-9A-Za-z-]{8,64}$")

_UUID_SHAPE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{0,63}$")


class AutoSleepConfig(BaseModel):
    """Auto-sleep on or off, its idle threshold, and the sessions kept awake.

    Fields:
        enabled: whether idle agent sessions are put to sleep. Default True.
        idle_minutes: how long a session must read ``idle`` continuously
            before it is put to sleep.
        unread_blocks_sleep: True keeps a session with the unread mark awake.
            False (the default) lets it sleep once it has been idle
            ``unread_idle_minutes`` (default 60); the mark stays on the asleep row.
        unread_idle_minutes: the idle limit for an unread session, used
            only when ``unread_blocks_sleep`` is False.
        keep_awake: ``session_uuid`` values of the sessions never put to
            sleep automatically.
        mac_awake_always: True holds the Mac's idle-sleep assertion (the #617
            ``caffeinate -i -w`` child) whatever the keep-awake list holds
            (issue #1897, the tray's Keep Mac Awake). Default False.
        pinned_by_device: RETIRED (issue #645, and no longer read by the
            sleep pass since 2026-09-30: pins block nothing). Kept in the model
            only so a stored block still parses.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    idle_minutes: int = Field(DEFAULT_IDLE_MINUTES, ge=MIN_IDLE_MINUTES, le=MAX_IDLE_MINUTES)
    unread_blocks_sleep: bool = DEFAULT_UNREAD_BLOCKS_SLEEP
    unread_idle_minutes: int = Field(
        DEFAULT_UNREAD_IDLE_MINUTES, ge=MIN_IDLE_MINUTES, le=MAX_IDLE_MINUTES
    )
    keep_awake: List[str] = Field(default_factory=list)
    mac_awake_always: bool = False
    pinned_by_device: Dict[str, List[str]] = Field(default_factory=dict)

    def mac_awake_demand(self) -> int:
        return len(self.keep_awake) + (1 if self.mac_awake_always else 0)

    @field_validator("keep_awake")
    @classmethod
    def _uuids(cls, value: List[str]) -> List[str]:
        if len(value) > MAX_KEEP_AWAKE:
            raise ValueError(f"at most {MAX_KEEP_AWAKE} sessions can be kept awake")
        seen: List[str] = []
        for item in value:
            if not isinstance(item, str) or not _UUID_SHAPE.match(item):
                raise ValueError("keep_awake holds session uuids only")
            if item not in seen:
                seen.append(item)
        return seen

    @field_validator("pinned_by_device")
    @classmethod
    def _device_pins(cls, value: Dict[str, List[str]]) -> Dict[str, List[str]]:
        if len(value) > MAX_PIN_DEVICES:
            raise ValueError(f"at most {MAX_PIN_DEVICES} devices")
        for device, names in value.items():
            if not _DEVICE_SHAPE.match(device):
                raise ValueError("a device id is 8 to 64 letters, digits or dashes")
            if len(names) > MAX_PINS_PER_DEVICE:
                raise ValueError(f"at most {MAX_PINS_PER_DEVICE} pins per device")
            for name in names:
                if not isinstance(name, str) or not name or len(name) > 128:
                    raise ValueError("a pinned name must be 1 to 128 characters")
        return value
