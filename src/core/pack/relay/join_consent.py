
from __future__ import annotations

import structlog

from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.relay import consent as consent_mod

logger = structlog.get_logger()


def accept_on_join() -> bool:
    wired = machines_runtime.wiring()
    if wired is None or wired.state.relay_consent().mode is not None:
        return False
    try:
        with consent_mod.WRITE_LOCK:
            wired.state.save_relay_consent(consent_mod.Consent(consent_mod.MODE_ALL))
            wired.runtime.set_restrictions({"may_receive_credentials": True, "may_receive_global_setup": True}, from_peer=False, sync_consent=False)
    except (OSError, ValueError) as exc:
        logger.warning("pack_join_consent_failed", error=type(exc).__name__)
        return False
    wired.sync_scopes()
    logger.info("pack_join_consent_accepted")
    return True
