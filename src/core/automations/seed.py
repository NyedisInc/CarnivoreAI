from __future__ import annotations

import structlog

from src.core.automations import models as m
from src.core.automations.store import AutomationStore

logger = structlog.get_logger()
SEED_KEY = "scrooge_weekly"
NAME = "scrooge weekly"
CRON = "0 7 * * 1"
TARGET = {"kind": "recipe", "recipe": "scrooge", "params": {}}


def apply(store: AutomationStore) -> bool:
    if store.seed_settled(SEED_KEY):
        return False
    try:
        store.create(name=NAME, cron=CRON, target=TARGET, delivery={"notify_on": "report"}, enabled=False,
                     created_by="seed", seed_key=SEED_KEY, misfire="skip")
    except m.AutomationInvalid as exc:
        logger.warning("automation_seed_refused", seed_key=SEED_KEY, code=exc.code)
        return False
    logger.info("automation_seeded", seed_key=SEED_KEY)
    return True
