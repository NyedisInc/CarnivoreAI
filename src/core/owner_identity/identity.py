
from __future__ import annotations

import os
import pwd
from typing import Optional

import structlog

logger = structlog.get_logger()

GECOS_FIELD_SEPARATOR = ","


def parse_gecos(gecos: Optional[str]) -> Optional[str]:
    if not gecos:
        return None
    name = gecos.split(GECOS_FIELD_SEPARATOR, 1)[0].strip()
    if not name or any(not ch.isprintable() for ch in name):
        return None
    return name


def os_account_full_name(uid: Optional[int] = None) -> Optional[str]:
    try:
        entry = pwd.getpwuid(os.getuid() if uid is None else uid)
    except KeyError:
        logger.info("owner_identity_no_passwd_entry")
        return None
    return parse_gecos(entry.pw_gecos)
