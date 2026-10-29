
from __future__ import annotations

from typing import Optional

from src.core.notifications import contracts
from src.core.notifications.sources import common

WRONG_CODE = "computer.wrong_code"
LINK_CERT = "computer.link_cert"


def wrong_code(event: str, addr: str) -> bool:
    return common.emit_if_sink(contracts.NotifyEvent(
        type_id=WRONG_CODE, kind="computer_wrong_code", title=common.type_title(WRONG_CODE), ts=common.now(),
        severity=contracts.SEVERITY_WARN, details=f"{event} from {addr}"[:200], instance_key=f"wrong_code:{event}:{common.now():.0f}"))


def link_cert(why: str, cert_sha: Optional[str] = None) -> bool:
    return common.emit_if_sink(contracts.NotifyEvent(
        type_id=LINK_CERT, kind="computer_link_cert", title=common.type_title(LINK_CERT), ts=common.now(),
        severity=contracts.SEVERITY_WARN, details=why[:200], instance_key=f"link_cert:{why}:{(cert_sha or '')[:12]}", open_item=True))
