
from __future__ import annotations

import gc

from src.core.perf_hooks import gc_tuning


def test_tune_after_startup_freezes_the_heap_and_sets_thresholds():
    saved = gc.get_threshold()
    gc.unfreeze()
    try:
        live = [object() for _ in range(1000)]
        assert gc.get_freeze_count() == 0
        assert gc_tuning.tune_after_startup() == gc_tuning.GC_THRESHOLDS
        assert gc.get_freeze_count() >= len(live)
    finally:
        gc.unfreeze()
        gc.set_threshold(*saved)
