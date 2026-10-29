
from __future__ import annotations

from typing import Awaitable, Callable

import structlog

from src.core.app_alerts import service as alerts
from src.core.app_alerts import constants as alert_const
from src.core.phone_link.pairing import PairingStore

logger = structlog.get_logger()

SETTING = "cd_repair_seen"
ALERT_KEY = "phone_link.repair"
ALERT_SOURCE = "phone_link"
TITLE_KEY = "app_alert.phone_link.repair.title"
DETAIL_KEY = "app_alert.phone_link.repair.detail"


class RepairGate:

    def __init__(self, *, pairing: PairingStore, revoke_device: Callable[[str], Awaitable[None]],
                 link_host: Callable[[], str] = lambda: "", on_done: Callable[[], None] = lambda: None) -> None:
        self._pairing, self._revoke, self._on_done = pairing, revoke_device, on_done
        self._link_host = link_host

    def seen(self) -> int:
        raw = self._pairing.setting(SETTING)
        return int(raw) if raw and raw.isdigit() else 0

    async def enforce(self, epoch: int) -> bool:
        if epoch <= self.seen():
            return False
        devices = self._pairing.devices_off_link(self._link_host())
        for device in devices:
            await self._revoke(device.id)
        self._pairing.set_setting(SETTING, str(epoch))
        if devices:
            alerts.raise_alert(ALERT_KEY, source=ALERT_SOURCE, severity=alert_const.SEV_WARN, title_key=TITLE_KEY,
                               detail_key=DETAIL_KEY, sticky=True, auto_resolve=False)
        logger.info("phone_link_repair_executed", revoked=len(devices), epoch=epoch)
        self._on_done()
        return True
