
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from src.core.backup_health import constants as K
from src.core.backup_health import vault_record
from src.core.backup_health.checks import FIRING, OK, UNKNOWN, Verdict


def check_vault(state_dir: Path, now: Optional[float] = None) -> List[Verdict]:
    record = vault_record.read(state_dir)
    facts = vault_record.evaluate(record, now=now if now is not None else time.time())
    keys = (K.KEY_VAULT_UNAVAILABLE, K.KEY_VAULT_STALE, K.KEY_VAULT_UNCOVERED, K.KEY_VAULT_OVER_CAP, K.KEY_VAULT_DAMAGED)
    if not record or not facts["active"]:
        return [Verdict(key, OK) for key in keys]
    down = facts["unavailable"]
    out = [Verdict(K.KEY_VAULT_UNAVAILABLE, FIRING, "error", K.TITLE_VAULT_UNAVAILABLE, K.DETAIL_VAULT_UNAVAILABLE,
                   {"reason": down}) if down else Verdict(K.KEY_VAULT_UNAVAILABLE, OK)]
    if down:
        out += [Verdict(K.KEY_VAULT_STALE, UNKNOWN), Verdict(K.KEY_VAULT_UNCOVERED, UNKNOWN)]
    else:
        hours = facts["stale_hours"]
        out.append(Verdict(K.KEY_VAULT_STALE, FIRING, "warn", K.TITLE_VAULT_STALE, K.DETAIL_VAULT_STALE,
                           {"hours": hours, "max_hours": int(vault_record.STALE_HOURS)}) if hours is not None
                   else Verdict(K.KEY_VAULT_STALE, OK))
        late = facts["uncovered_overdue"]
        out.append(Verdict(K.KEY_VAULT_UNCOVERED, FIRING, "warn", K.TITLE_VAULT_UNCOVERED, K.DETAIL_VAULT_UNCOVERED,
                           {"count": late, "on_disk": facts["on_disk"]}) if late
                   else Verdict(K.KEY_VAULT_UNCOVERED, OK if facts["known"] else UNKNOWN))
    out.append(Verdict(K.KEY_VAULT_OVER_CAP, FIRING, "warn", K.TITLE_VAULT_OVER_CAP, K.DETAIL_VAULT_OVER_CAP, {})
               if facts["over_cap"] else Verdict(K.KEY_VAULT_OVER_CAP, OK))
    out.append(Verdict(K.KEY_VAULT_DAMAGED, FIRING, "error", K.TITLE_VAULT_DAMAGED, K.DETAIL_VAULT_DAMAGED,
                       {"count": facts["damaged"]}) if facts["damaged"] else Verdict(K.KEY_VAULT_DAMAGED, OK))
    return out
