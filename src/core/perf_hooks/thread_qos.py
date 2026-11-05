
from __future__ import annotations

import ctypes
import ctypes.util
import sys

import structlog

logger = structlog.get_logger()

QOS_CLASS_USER_INTERACTIVE = 0x21


def request_user_interactive(label: str) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("System") or "libSystem.dylib", use_errno=True)
        fn = lib.pthread_set_qos_class_self_np
        fn.argtypes, fn.restype = [ctypes.c_uint, ctypes.c_int], ctypes.c_int
        rc = int(fn(QOS_CLASS_USER_INTERACTIVE, 0))
    except (OSError, AttributeError, ctypes.ArgumentError) as exc:
        logger.info("thread_qos_unavailable", thread=label, error=type(exc).__name__)
        return False
    logger.info("thread_qos_requested", thread=label, qos="user_interactive", rc=rc)
    return rc == 0
