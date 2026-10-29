
from __future__ import annotations

CATALOG_SIGNED_OUT_STATUS = 403


def client_status(host_status: int) -> int:
    return CATALOG_SIGNED_OUT_STATUS if host_status == 401 else host_status
