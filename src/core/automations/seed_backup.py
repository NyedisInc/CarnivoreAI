from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.backup_health import constants as K

logger = structlog.get_logger()
BUILTINS: Tuple[Tuple[str, str, str, str], ...] = (
    (K.HEALTH_SEED_KEY, K.HEALTH_AUTOMATION_NAME, K.HEALTH_CRON, "backup_health_check"),
)


def retire_catchup(store: AutomationStore, db_path: Optional[Path] = None) -> int:
    from src.core.app_alerts import service as alerts  # noqa: PLC0415

    gone = 0
    for row in store.list_all():
        target = row.get("target") or {}
        if row.get("seed_key") == K.RETIRED_CATCHUP_SEED_KEY or target.get("recipe") == K.RETIRED_CATCHUP_RECIPE:
            store.delete(row["automation_id"])
            logger.info("automation_retired", seed_key=row.get("seed_key"), name=row.get("name"))
            gone += 1
    for key in K.RETIRED_ALERT_KEYS:
        alerts.resolve(key, db_path=db_path)
    return gone


def apply(store: AutomationStore, db_path: Optional[Path] = None) -> List[str]:
    retire_catchup(store, db_path)
    created: List[str] = []
    for seed_key, name, cron, action in BUILTINS:
        if store.seed_settled(seed_key):
            continue
        try:
            store.create(name=name, cron=cron, target={"kind": "recipe", "recipe": action, "params": {}},
                         delivery={"notify_on": "failure"}, enabled=True, created_by="seed", seed_key=seed_key, misfire="skip")
        except m.AutomationInvalid as exc:
            logger.warning("automation_seed_refused", seed_key=seed_key, code=exc.code)
            continue
        logger.info("automation_seeded", seed_key=seed_key)
        created.append(seed_key)
    return created
