
from __future__ import annotations

import gc
from typing import Tuple

import structlog

logger = structlog.get_logger()

GC_THRESHOLDS: Tuple[int, int, int] = (5000, 20, 50)


def tune_after_startup() -> Tuple[int, int, int]:
    gc.collect()
    gc.freeze()
    gc.set_threshold(*GC_THRESHOLDS)
    logger.info("gc_tuned", frozen=gc.get_freeze_count(), thresholds=list(GC_THRESHOLDS))
    return gc.get_threshold()
