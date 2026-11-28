
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from src.core.app_alerts import kinds as alert_kinds
from src.core.backup_health import constants as K
from src.core.backup_health import vault_record
from src.core.backup_health.checks import FIRING, OK, UNKNOWN, Verdict


def check_vault(state_dir: Path, now: Optional[float] = None) -> List[Verdict]:
    record = vault_record.read(state_dir)
    facts = vault_record.evaluate(record, now=now if now is not None else time.time())
    keys = (K.KEY_VAULT_UNAVAILABLE, K.KEY_VAULT_STALE, K.KEY_VAULT_UNCOVERED, K.KEY_VAULT_OVER_CAP, K.KEY_VAULT_DAMAGED,
            K.KEY_VAULT_MASS_GONE, K.KEY_VAULT_FROZEN, K.KEY_VAULT_PURGE_UNVERIFIED, K.KEY_VAULT_SCRUB_DAMAGED, K.KEY_VAULT_RESTORE_FAILED, K.KEY_VAULT_LEDGER_UNREADABLE)
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
    gone = facts["mass_gone"]
    if gone and gone.get("count"):
        step = int(gone.get("step") or 0)
        key = K.KEY_VAULT_MASS_GONE if step == 0 else f"{K.KEY_VAULT_MASS_GONE}.{step}"
        out.append(Verdict(key, FIRING, "warn", K.TITLE_VAULT_MASS_GONE, K.DETAIL_VAULT_MASS_GONE,
                           {"count": int(gone["count"]), "samples": ", ".join(str(s) for s in gone.get("samples") or [])},
                           sticky=True, actions=(alert_kinds.clear_freeze_action(),) if facts["frozen"] else ()))
    else:
        out.append(Verdict(K.KEY_VAULT_MASS_GONE, OK, drop_actions=() if facts["frozen"] else (alert_kinds.CLEAR_FREEZE_ID,)))
    if facts["frozen"]:
        count = int(facts["frozen"].get("count") or 0)
        detail = K.DETAIL_VAULT_FROZEN_OVER_CAP if facts["frozen_over_cap"] else K.DETAIL_VAULT_FROZEN
        out.append(Verdict(K.KEY_VAULT_FROZEN, FIRING, "warn", K.TITLE_VAULT_FROZEN, detail, {"count": count}))
    else:
        out.append(Verdict(K.KEY_VAULT_FROZEN, OK))
    out += _offload_verdicts(facts["offload_alerts"])
    return out


def _offload_verdicts(alerts: dict) -> List[Verdict]:
    out: List[Verdict] = []
    for name, key, title, detail, count_of in (
        ("purge", K.KEY_VAULT_PURGE_UNVERIFIED, K.TITLE_VAULT_PURGE_UNVERIFIED, K.DETAIL_VAULT_PURGE_UNVERIFIED, "conversations"),
        ("scrub", K.KEY_VAULT_SCRUB_DAMAGED, K.TITLE_VAULT_SCRUB_DAMAGED, K.DETAIL_VAULT_SCRUB_DAMAGED, "blobs"),
        ("restore", K.KEY_VAULT_RESTORE_FAILED, K.TITLE_VAULT_RESTORE_FAILED, K.DETAIL_VAULT_RESTORE_FAILED, "conversations"),
        ("ledger", K.KEY_VAULT_LEDGER_UNREADABLE, K.TITLE_VAULT_LEDGER_UNREADABLE, K.DETAIL_VAULT_LEDGER_UNREADABLE, "conversations"),
    ):
        part = alerts.get(name) if isinstance(alerts.get(name), dict) else {}
        blobs = [str(b) for b in part.get("blobs") or []]
        if not blobs and not part.get("conversations"):
            out.append(Verdict(key, OK))
            continue
        seq = int(part.get("seq") or 0)
        params = {"count": len(part.get(count_of) or part.get("conversations") or []), "blobs": ", ".join(blobs[:3]) + (f" and {len(blobs) - 3} more" if len(blobs) > 3 else ""), "script": K.VAULT_REPAIR_SCRIPT,
                  "targets": ", ".join(str(c) for c in (part.get("conversations") or [])[:3]) + (f" and {len(part['conversations']) - 3} more" if len(part.get("conversations") or []) > 3 else "")}
        out.append(Verdict(key if seq == 0 else f"{key}.{seq}", FIRING, "error", title, detail, params, sticky=True))
    return out
